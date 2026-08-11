"""Developer-only transaction probe for the core persistence repositories."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from rag_api.db.models import (
    Chunk,
    Conversation,
    Message,
    MessageRole,
    RetrievalTerminalState,
    RetrievalTrace,
    RetrievalTraceChunk,
    SourceDocument,
    SourceType,
    SourceVersion,
    SourceVersionStatus,
    Widget,
)
from rag_api.db.repositories import (
    ChunkCreate,
    ConversationRepository,
    SourceRepository,
    TraceChunkCreate,
    TraceRepository,
    WidgetRepository,
)

COUNT_MODELS = (
    Widget,
    SourceDocument,
    SourceVersion,
    Chunk,
    Conversation,
    Message,
    RetrievalTrace,
    RetrievalTraceChunk,
)


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the developer schema probe.")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("The schema probe requires a postgresql+asyncpg DATABASE_URL.")
    return database_url


async def _counts(session: AsyncSession) -> dict[str, int]:
    values: dict[str, int] = {}
    for model in COUNT_MODELS:
        count = await session.scalar(select(func.count()).select_from(model))
        values[model.__tablename__] = int(count or 0)
    return values


async def run_probe() -> dict[str, object]:
    """Insert a complete repository chain and prove caller-owned rollback."""
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                widget = await WidgetRepository(session).create(
                    public_key_hash="0" * 64,
                    allowed_origins=("https://probe.example",),
                    display_config={"welcome": "Schema probe"},
                    handoff_config={"url": "https://probe.example/support"},
                )
                source_repository = SourceRepository(session)
                document = await source_repository.create_document(
                    source_type=SourceType.MARKDOWN,
                    source_location="upload://schema-probe/source.md",
                    title="Schema probe source",
                    tags=("probe",),
                )
                version = await source_repository.create_version(
                    document_id=document.id,
                    version_number=1,
                    content_hash="1" * 64,
                    raw_object_key="probe/source.md",
                    metadata={"probe": True},
                )
                await source_repository.record_embedding_profile(
                    version_id=version.id,
                    provider_id="schema-probe",
                    model_id="deterministic-fixture",
                    dimension=3,
                )
                chunks = await source_repository.add_chunks(
                    version_id=version.id,
                    chunks=(
                        ChunkCreate(
                            text="The schema probe validates one grounded support chunk.",
                            token_count=9,
                            heading="Probe",
                            category="support",
                            tags=("probe",),
                            embedding=(0.1, 0.2, 0.3),
                            embedding_dimension=3,
                        ),
                    ),
                )
                await source_repository.transition_version(
                    version.id,
                    SourceVersionStatus.PROCESSING,
                )
                await source_repository.transition_version(
                    version.id,
                    SourceVersionStatus.INDEXED,
                )
                await source_repository.set_active_version(
                    document_id=document.id,
                    version_id=version.id,
                )

                conversation_repository = ConversationRepository(session)
                conversation = await conversation_repository.create(
                    widget_id=widget.id,
                    visitor_session_id="schema-probe-session",
                    metadata={"probe": True},
                )
                await conversation_repository.append_message(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content="What does the schema probe validate?",
                )
                await conversation_repository.append_message(
                    conversation_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    content="It validates the core persistence chain.",
                )

                trace_repository = TraceRepository(session)
                trace = await trace_repository.create(
                    request_id=uuid.uuid4(),
                    conversation_id=conversation.id,
                    model_profile_id=uuid.uuid4(),
                    terminal_state=RetrievalTerminalState.ANSWERED,
                    metadata={"probe": True},
                )
                await trace_repository.attach_chunks(
                    trace_id=trace.id,
                    chunks=(TraceChunkCreate(chunk_id=chunks[0].id, rank=1, score=0.9),),
                )
                inserted = await _counts(session)
            finally:
                await session.close()
                await transaction.rollback()

        async with AsyncSession(engine) as verification_session:
            after_rollback = await _counts(verification_session)
        if any(after_rollback.values()):
            raise RuntimeError("Schema probe rollback left persisted fixture rows.")
        return {
            "event": "core_schema_probe_complete",
            "inserted_counts": inserted,
            "post_rollback_counts": after_rollback,
            "rolled_back": True,
        }
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and print only non-sensitive row-count evidence."""
    if argv:
        raise SystemExit("The schema probe does not accept arguments.")
    print(json.dumps(asyncio.run(run_probe()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
