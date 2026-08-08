"""Opt-in developer probe for real Vertex embeddings and pgvector persistence."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence

from rag_providers import (
    EmbeddingRequest,
    EmbeddingTask,
    FakeGenerationAdapter,
    ProviderOrchestrator,
    RequestBudget,
    VertexEmbeddingAdapter,
    VertexEmbeddingConfig,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from rag_api.db.models import Chunk, SourceType
from rag_api.db.repositories import ChunkCreate, SourceRepository

DOCUMENT_TEXT = "Reset the demo device from Settings, then choose Restore defaults."
QUERY_TEXT = "How do I reset the demo device?"


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if value is None or not value.startswith("postgresql+asyncpg://"):
        raise RuntimeError(
            "DATABASE_URL must select a disposable PostgreSQL database through asyncpg."
        )
    return value


async def run_probe() -> dict[str, object]:
    """Embed fixed text, store it transactionally, and report only safe metadata."""
    if os.getenv("RUN_VERTEX_EMBEDDING_INTEGRATION") != "1":
        raise RuntimeError(
            "Set RUN_VERTEX_EMBEDDING_INTEGRATION=1 to acknowledge the billed Vertex call."
        )
    adapter = VertexEmbeddingAdapter(VertexEmbeddingConfig.from_environment())
    runtime = ProviderOrchestrator(generation=FakeGenerationAdapter(), embedding=adapter)
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        document_result = await runtime.embed(
            EmbeddingRequest(
                texts=(DOCUMENT_TEXT,),
                budget=RequestBudget(timeout_seconds=30, max_input_tokens=128),
                task=EmbeddingTask.RETRIEVAL_DOCUMENT,
            )
        )
        query_result = await runtime.embed(
            EmbeddingRequest(
                texts=(QUERY_TEXT,),
                budget=RequestBudget(timeout_seconds=30, max_input_tokens=128),
                task=EmbeddingTask.RETRIEVAL_QUERY,
            )
        )
        if (
            document_result.metadata.model_id != query_result.metadata.model_id
            or document_result.dimension != query_result.dimension
        ):
            raise RuntimeError("Document and query embedding configurations diverged.")

        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                repository = SourceRepository(session)
                document = await repository.create_document(
                    source_type=SourceType.TXT,
                    source_location="probe://vertex-embedding/fixture.txt",
                    title="Vertex embedding probe fixture",
                    tags=("probe",),
                )
                version = await repository.create_version(
                    document_id=document.id,
                    version_number=1,
                    content_hash="vertex-embedding-probe",
                    metadata={"probe": True},
                )
                await repository.record_embedding_profile(
                    version_id=version.id,
                    **adapter.source_version_metadata(),
                )
                chunks = await repository.add_chunks(
                    version_id=version.id,
                    chunks=(
                        ChunkCreate(
                            text=DOCUMENT_TEXT,
                            token_count=document_result.metadata.token_usage.input_tokens,
                            metadata={"probe": True},
                            embedding=document_result.vectors[0],
                            embedding_dimension=document_result.dimension,
                        ),
                    ),
                )
                stored_dimension = await session.scalar(
                    text("SELECT vector_dims(embedding) FROM rag_app.chunk WHERE id = :chunk_id"),
                    {"chunk_id": chunks[0].id},
                )
                stored_metadata = version.metadata_json["embedding"]
            finally:
                await session.close()
                await transaction.rollback()

        async with AsyncSession(engine) as verification_session:
            fixture_remaining = await verification_session.scalar(
                select(Chunk.id).where(Chunk.id == chunks[0].id)
            )
        if fixture_remaining is not None:
            raise RuntimeError("Embedding probe rollback left a persisted fixture.")
        return {
            "event": "vertex_embedding_probe_complete",
            "provider_id": document_result.metadata.provider_id,
            "model_id": document_result.metadata.model_id,
            "configured_dimension": document_result.dimension,
            "stored_dimension": int(stored_dimension),
            "source_version_embedding": stored_metadata,
            "document_vector_count": len(document_result.vectors),
            "query_vector_count": len(query_result.vectors),
            "rolled_back": True,
        }
    finally:
        await engine.dispose()
        await adapter.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise SystemExit("The Vertex embedding probe does not accept arguments.")
    print(json.dumps(asyncio.run(run_probe()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
