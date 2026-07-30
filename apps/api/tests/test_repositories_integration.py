from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
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
    IllegalSourceVersionTransition,
    SourceRepository,
    TraceChunkCreate,
    TraceRepository,
    WidgetRepository,
)
from rag_api.migrations import MigrationSettings, upgrade
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(autouse=True)
def clean_core_tables(postgres_database_url: str) -> Iterator[None]:
    """Keep repository cases independent while sharing one Docker database."""
    upgrade(MigrationSettings(database_url=postgres_database_url))
    engine = create_engine(postgres_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE "
                "rag_app.retrieval_trace, rag_app.source_document, rag_app.widget "
                "CASCADE"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE "
                "rag_app.retrieval_trace, rag_app.source_document, rag_app.widget "
                "CASCADE"
            )
        )
    engine.dispose()


@pytest.fixture
async def async_engine(postgres_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        postgres_database_url.replace("+pg8000", "+asyncpg"),
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@dataclass(frozen=True)
class Chain:
    widget_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    parent_chunk_id: uuid.UUID
    child_chunk_id: uuid.UUID
    conversation_id: uuid.UUID
    trace_id: uuid.UUID


async def create_complete_chain(session: AsyncSession, suffix: str) -> Chain:
    widget = await WidgetRepository(session).create(
        public_key_hash=f"{suffix:0>64}",
        allowed_origins=("https://support.example",),
        display_config={"welcome": "Hello"},
        handoff_config={"email": "support@example.com"},
    )
    source_repository = SourceRepository(session)
    document = await source_repository.create_document(
        source_type=SourceType.MARKDOWN,
        source_location=f"upload://manuals/{suffix}.md",
        title=f"Support manual {suffix}",
        tags=("support", suffix),
    )
    version = await source_repository.create_version(
        document_id=document.id,
        version_number=1,
        content_hash=f"{suffix:0>64}",
        raw_object_key=f"sources/{document.id}/1.md",
        metadata={"language": "en"},
    )
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    chunks = await source_repository.add_chunks(
        version_id=version.id,
        chunks=(
            ChunkCreate(
                id=parent_id,
                text="Resetting your account password",
                token_count=5,
                heading="Account access",
                category="accounts",
                tags=("password",),
                metadata={"kind": "parent"},
                embedding=(0.1, 0.2, 0.3),
                embedding_dimension=3,
            ),
            ChunkCreate(
                id=child_id,
                parent_chunk_id=parent_id,
                text="Use the reset link sent to your verified email address.",
                token_count=10,
                heading="Reset steps",
                category="accounts",
                tags=("password",),
                metadata={"kind": "child"},
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
        visitor_session_id=f"visitor-{suffix}",
        metadata={"locale": "en"},
    )
    await conversation_repository.append_message(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content="How do I reset my password?",
    )
    await conversation_repository.append_message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="Use the reset link sent to your verified email.",
        metadata={"grounded": True},
    )

    trace_repository = TraceRepository(session)
    trace = await trace_repository.create(
        request_id=uuid.uuid4(),
        conversation_id=conversation.id,
        model_profile_id=uuid.uuid4(),
        terminal_state=RetrievalTerminalState.ANSWERED,
        metadata={"retrieval": "baseline"},
    )
    await trace_repository.attach_chunks(
        trace_id=trace.id,
        chunks=(
            TraceChunkCreate(chunk_id=chunks[1].id, rank=1, score=0.92),
            TraceChunkCreate(chunk_id=chunks[0].id, rank=2, score=0.81),
        ),
    )
    return Chain(
        widget_id=widget.id,
        document_id=document.id,
        version_id=version.id,
        parent_chunk_id=chunks[0].id,
        child_chunk_id=chunks[1].id,
        conversation_id=conversation.id,
        trace_id=trace.id,
    )


@pytest.mark.anyio
async def test_complete_chain_creation_and_retrieval(async_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        chain = await create_complete_chain(session, "complete")

    async with session_factory() as session:
        widget = await WidgetRepository(session).get_by_key_hash(f"{'complete':0>64}")
        document = await session.get(SourceDocument, chain.document_id)
        version = await session.get(SourceVersion, chain.version_id)
        chunks = (
            await session.scalars(
                select(Chunk)
                .where(Chunk.source_version_id == chain.version_id)
                .order_by(Chunk.parent_chunk_id.nulls_first())
            )
        ).all()
        messages = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == chain.conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
        links = (
            await session.scalars(
                select(RetrievalTraceChunk)
                .where(RetrievalTraceChunk.trace_id == chain.trace_id)
                .order_by(RetrievalTraceChunk.rank)
            )
        ).all()

    assert widget is not None and widget.id == chain.widget_id
    assert document is not None and document.active_version_id == chain.version_id
    assert document.source_location == "upload://manuals/complete.md"
    assert version is not None and version.status is SourceVersionStatus.INDEXED
    assert len(chunks) == 2
    assert chunks[1].parent_chunk_id == chain.parent_chunk_id
    assert str(chunks[0].full_text)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert [(link.rank, link.chunk_id) for link in links] == [
        (1, chain.child_chunk_id),
        (2, chain.parent_chunk_id),
    ]


@pytest.mark.anyio
async def test_invalid_status_and_illegal_transitions_are_rejected(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        source_repository = SourceRepository(session)
        document = await source_repository.create_document(
            source_type=SourceType.TXT,
            source_location="upload://fixtures/status.txt",
            title="Status fixture",
        )
        version = await source_repository.create_version(
            document_id=document.id,
            version_number=1,
            content_hash="status",
        )
        with pytest.raises(IllegalSourceVersionTransition, match="queued to indexed"):
            await source_repository.transition_version(
                version.id,
                SourceVersionStatus.INDEXED,
            )
        with pytest.raises(ValueError, match="requires a nonblank error"):
            await source_repository.transition_version(
                version.id,
                SourceVersionStatus.FAILED,
            )

    async with session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE rag_app.source_version "
                    "SET status = 'not-a-status' WHERE id = :version_id"
                ),
                {"version_id": version.id},
            )
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("UPDATE rag_app.source_version SET status = 'failed' WHERE id = :version_id"),
                {"version_id": version.id},
            )
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="illegal source version transition"):
            await session.execute(
                text("UPDATE rag_app.source_version SET status = 'indexed' WHERE id = :version_id"),
                {"version_id": version.id},
            )
            await session.flush()
        await session.rollback()

    async with session_factory.begin() as session:
        failed = await SourceRepository(session).transition_version(
            version.id,
            SourceVersionStatus.FAILED,
            error="Source download failed.",
        )
        assert failed.error == "Source download failed."


@pytest.mark.anyio
async def test_cross_document_and_cross_version_chunk_ownership_is_rejected(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        repository = SourceRepository(session)
        first_document = await repository.create_document(
            source_type=SourceType.TXT,
            source_location="upload://fixtures/first.txt",
            title="First",
        )
        first_version = await repository.create_version(
            document_id=first_document.id,
            version_number=1,
            content_hash="first",
        )
        parent = (
            await repository.add_chunks(
                version_id=first_version.id,
                chunks=(ChunkCreate(text="First parent", token_count=2),),
            )
        )[0]
        second_document = await repository.create_document(
            source_type=SourceType.TXT,
            source_location="upload://fixtures/second.txt",
            title="Second",
        )
        second_version = await repository.create_version(
            document_id=second_document.id,
            version_number=1,
            content_hash="second",
        )

    async with session_factory() as session:
        session.add(
            Chunk(
                document_id=first_document.id,
                source_version_id=second_version.id,
                text="Mismatched ownership",
                token_count=2,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        repository = SourceRepository(session)
        with pytest.raises(IntegrityError):
            await repository.add_chunks(
                version_id=second_version.id,
                chunks=(
                    ChunkCreate(
                        parent_chunk_id=parent.id,
                        text="Cross-version child",
                        token_count=2,
                    ),
                ),
            )
        await session.rollback()


@pytest.mark.anyio
async def test_only_one_indexed_version_per_document(async_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        repository = SourceRepository(session)
        document = await repository.create_document(
            source_type=SourceType.PDF,
            source_location="upload://manuals/versioned.pdf",
            title="Versioned manual",
        )
        first = await repository.create_version(
            document_id=document.id,
            version_number=1,
            content_hash="one",
        )
        second = await repository.create_version(
            document_id=document.id,
            version_number=2,
            content_hash="two",
        )
        await repository.transition_version(first.id, SourceVersionStatus.PROCESSING)
        await repository.transition_version(first.id, SourceVersionStatus.INDEXED)
        await repository.transition_version(second.id, SourceVersionStatus.PROCESSING)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await SourceRepository(session).transition_version(
                second.id,
                SourceVersionStatus.INDEXED,
            )
        await session.rollback()


@pytest.mark.anyio
async def test_active_version_must_belong_to_its_document(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        repository = SourceRepository(session)
        first_document = await repository.create_document(
            source_type=SourceType.TXT,
            source_location="upload://fixtures/first-owner.txt",
            title="First active-version owner",
        )
        second_document = await repository.create_document(
            source_type=SourceType.TXT,
            source_location="upload://fixtures/second-owner.txt",
            title="Second active-version owner",
        )
        second_version = await repository.create_version(
            document_id=second_document.id,
            version_number=1,
            content_hash="second-active",
        )

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "UPDATE rag_app.source_document "
                    "SET active_version_id = :version_id WHERE id = :document_id"
                ),
                {
                    "document_id": first_document.id,
                    "version_id": second_version.id,
                },
            )
            await session.flush()
        await session.rollback()


@pytest.mark.anyio
async def test_embedding_dimension_and_json_object_constraints(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        repository = SourceRepository(session)
        document = await repository.create_document(
            source_type=SourceType.URL,
            source_location="https://support.example/embedding",
            title="Embedding fixture",
        )
        version = await repository.create_version(
            document_id=document.id,
            version_number=1,
            content_hash="embedding",
        )

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await SourceRepository(session).add_chunks(
                version_id=version.id,
                chunks=(
                    ChunkCreate(
                        text="Wrong dimension",
                        token_count=2,
                        embedding=(0.1, 0.2, 0.3),
                        embedding_dimension=2,
                    ),
                ),
            )
        await session.rollback()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO rag_app.chunk "
                    "(document_id, source_version_id, text, token_count, metadata) "
                    "VALUES (:document_id, :version_id, 'Bad metadata', 2, '[]'::jsonb)"
                ),
                {"document_id": document.id, "version_id": version.id},
            )
            await session.flush()
        await session.rollback()


@pytest.mark.anyio
async def test_cascades_preserve_trace_but_remove_deleted_chunk_links(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        chain = await create_complete_chain(session, "cascade")

    async with session_factory.begin() as session:
        await session.execute(delete(Chunk).where(Chunk.id == chain.child_chunk_id))

    async with session_factory() as session:
        link_count = await session.scalar(
            select(func.count())
            .select_from(RetrievalTraceChunk)
            .where(RetrievalTraceChunk.trace_id == chain.trace_id)
        )
        assert link_count == 1
        assert await session.get(RetrievalTrace, chain.trace_id) is not None

    async with session_factory.begin() as session:
        await SourceRepository(session).delete_document(chain.document_id)
        widget = await session.get(Widget, chain.widget_id)
        assert widget is not None
        await session.delete(widget)

    async with session_factory() as session:
        assert await session.get(SourceDocument, chain.document_id) is None
        assert await session.get(SourceVersion, chain.version_id) is None
        assert await session.get(Chunk, chain.parent_chunk_id) is None
        assert await session.get(Conversation, chain.conversation_id) is None
        message_count = await session.scalar(select(func.count()).select_from(Message))
        link_count = await session.scalar(
            select(func.count())
            .select_from(RetrievalTraceChunk)
            .where(RetrievalTraceChunk.trace_id == chain.trace_id)
        )
        trace = await session.get(RetrievalTrace, chain.trace_id)
    assert message_count == 0
    assert link_count == 0
    assert trace is not None and trace.conversation_id is None


@pytest.mark.anyio
async def test_repository_flushes_remain_caller_rollback_controlled(
    async_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    key_hash = "rollback".zfill(64)
    async with session_factory() as session:
        await WidgetRepository(session).create(public_key_hash=key_hash)
        count_before_rollback = await session.scalar(select(func.count()).select_from(Widget))
        assert count_before_rollback == 1
        await session.rollback()

    async with session_factory() as session:
        assert await WidgetRepository(session).get_by_key_hash(key_hash) is None
