"""Transaction-neutral async repositories for the core persistence schema."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from rag_api.db.models import (
    AdminUser,
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


class RepositoryEntityNotFound(LookupError):
    """Raised when a requested persistence entity does not exist."""


class IllegalSourceVersionTransition(ValueError):
    """Raised before flushing a source-version transition disallowed by the lifecycle."""


class AdminUserRepository:
    """Idempotently map verified Supabase subjects to the single v1 admin role."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_by_supabase_user_id(
        self,
        supabase_user_id: uuid.UUID,
    ) -> AdminUser:
        statement = (
            insert(AdminUser)
            .values(supabase_user_id=supabase_user_id, role="admin")
            .on_conflict_do_nothing(index_elements=[AdminUser.supabase_user_id])
            .returning(AdminUser)
        )
        created = await self._session.scalar(statement)
        if created is not None:
            await self._session.flush()
            return created

        existing = await self._session.scalar(
            select(AdminUser).where(AdminUser.supabase_user_id == supabase_user_id)
        )
        if existing is None:
            raise RepositoryEntityNotFound(
                f"Administrator mapping for subject {supabase_user_id} was not found."
            )
        return existing


LEGAL_SOURCE_VERSION_TRANSITIONS: dict[SourceVersionStatus, frozenset[SourceVersionStatus]] = {
    SourceVersionStatus.QUEUED: frozenset(
        {SourceVersionStatus.PROCESSING, SourceVersionStatus.FAILED}
    ),
    SourceVersionStatus.PROCESSING: frozenset(
        {SourceVersionStatus.INDEXED, SourceVersionStatus.FAILED}
    ),
    SourceVersionStatus.INDEXED: frozenset({SourceVersionStatus.SUPERSEDED}),
    SourceVersionStatus.FAILED: frozenset(),
    SourceVersionStatus.SUPERSEDED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ChunkCreate:
    """Typed values for one chunk added to a source version."""

    text: str
    token_count: int
    parent_chunk_id: uuid.UUID | None = None
    page_number: int | None = None
    heading: str | None = None
    category: str | None = None
    tags: Sequence[str] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Sequence[float] | None = None
    embedding_dimension: int | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True, slots=True)
class TraceChunkCreate:
    """Ordered score attached to a retrieval trace."""

    chunk_id: uuid.UUID
    rank: int
    score: float


class WidgetRepository:
    """Persistence operations for public widget configuration."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        public_key_hash: str,
        enabled: bool = True,
        allowed_origins: Sequence[str] = (),
        display_config: dict[str, Any] | None = None,
        handoff_config: dict[str, Any] | None = None,
    ) -> Widget:
        widget = Widget(
            public_key_hash=public_key_hash,
            enabled=enabled,
            allowed_origins=list(allowed_origins),
            display_config=dict(display_config or {}),
            handoff_config=dict(handoff_config or {}),
        )
        self._session.add(widget)
        await self._session.flush()
        return widget

    async def get_by_key_hash(self, public_key_hash: str) -> Widget | None:
        return cast(
            Widget | None,
            await self._session.scalar(
                select(Widget).where(Widget.public_key_hash == public_key_hash)
            ),
        )


class SourceRepository:
    """Persistence operations for logical documents and immutable versions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_document(
        self,
        *,
        source_type: SourceType,
        source_location: str,
        title: str,
        tags: Sequence[str] = (),
        document_id: uuid.UUID | None = None,
    ) -> SourceDocument:
        document = SourceDocument(
            id=document_id or uuid.uuid4(),
            source_type=source_type,
            source_location=source_location,
            title=title,
            tags=list(tags),
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def create_version(
        self,
        *,
        document_id: uuid.UUID,
        version_number: int,
        content_hash: str | None = None,
        raw_object_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceVersion:
        version = SourceVersion(
            document_id=document_id,
            version_number=version_number,
            status=SourceVersionStatus.QUEUED,
            content_hash=content_hash,
            raw_object_key=raw_object_key,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(version)
        await self._session.flush()
        return version

    async def add_chunks(
        self,
        *,
        version_id: uuid.UUID,
        chunks: Sequence[ChunkCreate],
    ) -> list[Chunk]:
        version = await self._session.get(SourceVersion, version_id)
        if version is None:
            raise RepositoryEntityNotFound(f"Source version {version_id} was not found.")

        has_embeddings = any(chunk.embedding is not None for chunk in chunks)
        embedding_profile = version.metadata_json.get("embedding")
        if has_embeddings and embedding_profile is None:
            raise ValueError(
                "Source version embedding profile must be recorded before adding embedded chunks."
            )
        if embedding_profile is not None:
            if not isinstance(embedding_profile, dict):
                raise ValueError("Source version embedding metadata must be an object.")
            recorded_dimension = embedding_profile.get("dimension")
            if type(recorded_dimension) is not int or recorded_dimension <= 0:
                raise ValueError(
                    "Source version embedding metadata requires a positive integer dimension."
                )
            if any(
                chunk.embedding is not None and chunk.embedding_dimension != recorded_dimension
                for chunk in chunks
            ):
                raise ValueError(
                    "Chunk embedding dimension must match the source version embedding profile."
                )

        records = [
            Chunk(
                id=chunk.id,
                document_id=version.document_id,
                source_version_id=version.id,
                parent_chunk_id=chunk.parent_chunk_id,
                text=chunk.text,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                heading=chunk.heading,
                category=chunk.category,
                tags=list(chunk.tags),
                metadata_json=dict(chunk.metadata),
                embedding=list(chunk.embedding) if chunk.embedding is not None else None,
                embedding_dimension=chunk.embedding_dimension,
            )
            for chunk in chunks
        ]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def record_embedding_profile(
        self,
        *,
        version_id: uuid.UUID,
        provider_id: str,
        model_id: str,
        dimension: int,
    ) -> SourceVersion:
        """Persist the immutable embedding identity used by one source version."""
        if not provider_id.strip() or not model_id.strip():
            raise ValueError("Embedding provider and model IDs must not be blank.")
        if dimension <= 0:
            raise ValueError("Embedding dimension must be greater than zero.")
        version = await self._session.scalar(
            select(SourceVersion).where(SourceVersion.id == version_id).with_for_update()
        )
        if version is None:
            raise RepositoryEntityNotFound(f"Source version {version_id} was not found.")
        profile: dict[str, object] = {
            "provider_id": provider_id,
            "model_id": model_id,
            "dimension": dimension,
        }
        existing = version.metadata_json.get("embedding")
        if existing is not None and existing != profile:
            raise ValueError("Source version embedding profile is immutable once recorded.")
        version.metadata_json = {**version.metadata_json, "embedding": profile}
        await self._session.flush()
        return version

    async def transition_version(
        self,
        version_id: uuid.UUID,
        target: SourceVersionStatus,
        *,
        error: str | None = None,
        content_hash: str | None = None,
    ) -> SourceVersion:
        version = await self._session.scalar(
            select(SourceVersion).where(SourceVersion.id == version_id).with_for_update()
        )
        if version is None:
            raise RepositoryEntityNotFound(f"Source version {version_id} was not found.")
        if target not in LEGAL_SOURCE_VERSION_TRANSITIONS[version.status]:
            raise IllegalSourceVersionTransition(
                f"Source version cannot transition from {version.status.value} to {target.value}."
            )
        if target is SourceVersionStatus.FAILED and (error is None or not error.strip()):
            raise ValueError("A failed source version requires a nonblank error.")
        if target is not SourceVersionStatus.FAILED and error is not None:
            raise ValueError("Only a failed source version can store an error.")
        if content_hash is not None:
            if not content_hash.strip():
                raise ValueError("A source content hash must be nonblank.")
            version.content_hash = content_hash
        if target is SourceVersionStatus.INDEXED and version.content_hash is None:
            raise ValueError("An indexed source version requires a content hash.")
        version.status = target
        version.error = error
        await self._session.flush()
        return version

    async def set_active_version(
        self,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> SourceDocument:
        document = await self._session.scalar(
            select(SourceDocument).where(SourceDocument.id == document_id).with_for_update()
        )
        version = await self._session.get(SourceVersion, version_id)
        if document is None:
            raise RepositoryEntityNotFound(f"Source document {document_id} was not found.")
        if version is None or version.document_id != document.id:
            raise RepositoryEntityNotFound(
                f"Source version {version_id} does not belong to document {document_id}."
            )
        if version.status is not SourceVersionStatus.INDEXED:
            raise ValueError("Only an indexed source version can become active.")
        document.active_version_id = version.id
        await self._session.flush()
        return document

    async def delete_document(self, document_id: uuid.UUID) -> None:
        document = await self._session.get(SourceDocument, document_id)
        if document is None:
            raise RepositoryEntityNotFound(f"Source document {document_id} was not found.")
        await self._session.delete(document)
        await self._session.flush()


class ConversationRepository:
    """Persistence operations for widget conversations and messages."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        widget_id: uuid.UUID,
        visitor_session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        conversation = Conversation(
            widget_id=widget_id,
            visitor_session_id=visitor_session_id,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def append_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(message)
        await self._session.flush()
        return message


class TraceRepository:
    """Persistence operations for minimal request and candidate traces."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        request_id: uuid.UUID,
        model_profile_id: uuid.UUID,
        terminal_state: RetrievalTerminalState,
        conversation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RetrievalTrace:
        trace = RetrievalTrace(
            request_id=request_id,
            conversation_id=conversation_id,
            model_profile_id=model_profile_id,
            terminal_state=terminal_state,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(trace)
        await self._session.flush()
        return trace

    async def attach_chunks(
        self,
        *,
        trace_id: uuid.UUID,
        chunks: Sequence[TraceChunkCreate],
    ) -> list[RetrievalTraceChunk]:
        links = [
            RetrievalTraceChunk(
                trace_id=trace_id,
                chunk_id=chunk.chunk_id,
                rank=chunk.rank,
                score=chunk.score,
            )
            for chunk in chunks
        ]
        self._session.add_all(links)
        await self._session.flush()
        return links
