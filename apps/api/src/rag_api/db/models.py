"""Typed SQLAlchemy models for the grounded-chat persistence baseline."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

APPLICATION_SCHEMA = "rag_app"


class SourceType(StrEnum):
    """Supported source kinds for the curated v1 knowledge base."""

    TXT = "txt"
    MARKDOWN = "markdown"
    PDF = "pdf"
    URL = "url"


class SourceVersionStatus(StrEnum):
    """Lifecycle states for an immutable source version."""

    QUEUED = "queued"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class MessageRole(StrEnum):
    """Visitor and assistant roles stored in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"


class RetrievalTerminalState(StrEnum):
    """Final outcomes for the minimal retrieval trace."""

    ANSWERED = "answered"
    ABSTAINED = "abstained"
    FAILED = "failed"


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


source_type_enum = Enum(
    SourceType,
    name="source_type",
    schema=APPLICATION_SCHEMA,
    values_callable=_enum_values,
)
source_version_status_enum = Enum(
    SourceVersionStatus,
    name="source_version_status",
    schema=APPLICATION_SCHEMA,
    values_callable=_enum_values,
)
message_role_enum = Enum(
    MessageRole,
    name="message_role",
    schema=APPLICATION_SCHEMA,
    values_callable=_enum_values,
)
retrieval_terminal_state_enum = Enum(
    RetrievalTerminalState,
    name="retrieval_terminal_state",
    schema=APPLICATION_SCHEMA,
    values_callable=_enum_values,
)


class Base(DeclarativeBase):
    """Declarative base for application-owned tables."""

    type_annotation_map = {dict[str, Any]: JSONB}


class TimestampMixin:
    """Server-generated UTC timestamps shared by mutable records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("statement_timestamp()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Widget(TimestampMixin, Base):
    """Public widget configuration without storing the public key itself."""

    __tablename__ = "widget"
    __table_args__ = (
        CheckConstraint("length(btrim(public_key_hash)) > 0", name="ck_widget_key_hash"),
        CheckConstraint(
            "array_position(allowed_origins, '') IS NULL",
            name="ck_widget_allowed_origins_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(display_config) = 'object'",
            name="ck_widget_display_config_object",
        ),
        CheckConstraint(
            "jsonb_typeof(handoff_config) = 'object'",
            name="ck_widget_handoff_config_object",
        ),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    public_key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa.text("true"),
        nullable=False,
    )
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=sa.text("'{}'::text[]"),
        nullable=False,
    )
    display_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    handoff_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


class SourceDocument(TimestampMixin, Base):
    """Stable logical source across immutable content versions."""

    __tablename__ = "source_document"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(source_location)) > 0",
            name="ck_source_document_location",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_source_document_title"),
        CheckConstraint(
            "array_position(tags, '') IS NULL",
            name="ck_source_document_tags_nonempty",
        ),
        ForeignKeyConstraint(
            ["id", "active_version_id"],
            [
                f"{APPLICATION_SCHEMA}.source_version.document_id",
                f"{APPLICATION_SCHEMA}.source_version.id",
            ],
            name="fk_source_document_active_version",
            use_alter=True,
        ),
        Index("ix_source_document_active_version_id", "active_version_id"),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    source_type: Mapped[SourceType] = mapped_column(source_type_enum, nullable=False)
    source_location: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=sa.text("'{}'::text[]"),
        nullable=False,
    )
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )


class SourceVersion(TimestampMixin, Base):
    """One immutable ingestion attempt for a logical source."""

    __tablename__ = "source_version"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_source_version_number_positive"),
        CheckConstraint(
            "content_hash IS NULL OR length(btrim(content_hash)) > 0",
            name="ck_source_version_content_hash",
        ),
        CheckConstraint(
            "status NOT IN ('indexed', 'superseded') OR content_hash IS NOT NULL",
            name="ck_source_version_indexed_hash",
        ),
        CheckConstraint(
            "raw_object_key IS NULL OR length(btrim(raw_object_key)) > 0",
            name="ck_source_version_raw_object_key",
        ),
        CheckConstraint(
            "(status = 'failed' AND error IS NOT NULL AND length(btrim(error)) > 0) "
            "OR (status <> 'failed' AND error IS NULL)",
            name="ck_source_version_error_matches_status",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_source_version_metadata_object",
        ),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_source_version_document_number",
        ),
        UniqueConstraint("document_id", "id", name="uq_source_version_document_id"),
        Index("ix_source_version_document_status", "document_id", "status"),
        Index(
            "uq_source_version_one_indexed",
            "document_id",
            unique=True,
            postgresql_where=sa.text("status = 'indexed'"),
        ),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.source_document.id",
            name="fk_source_version_document",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SourceVersionStatus] = mapped_column(
        source_version_status_enum,
        default=SourceVersionStatus.QUEUED,
        server_default=sa.text("'queued'"),
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


class Chunk(Base):
    """Searchable source text tied to exactly one source version."""

    __tablename__ = "chunk"
    __table_args__ = (
        CheckConstraint("length(btrim(text)) > 0", name="ck_chunk_text"),
        CheckConstraint("token_count > 0", name="ck_chunk_token_count_positive"),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_chunk_page_number_positive",
        ),
        CheckConstraint(
            "heading IS NULL OR length(btrim(heading)) > 0",
            name="ck_chunk_heading",
        ),
        CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_chunk_category",
        ),
        CheckConstraint(
            "array_position(tags, '') IS NULL",
            name="ck_chunk_tags_nonempty",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_chunk_metadata_object"),
        CheckConstraint(
            "(embedding IS NULL AND embedding_dimension IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_dimension > 0 "
            "AND vector_dims(embedding) = embedding_dimension)",
            name="ck_chunk_embedding_dimension",
        ),
        UniqueConstraint(
            "document_id",
            "source_version_id",
            "id",
            name="uq_chunk_document_version_id",
        ),
        ForeignKeyConstraint(
            ["document_id", "source_version_id"],
            [
                f"{APPLICATION_SCHEMA}.source_version.document_id",
                f"{APPLICATION_SCHEMA}.source_version.id",
            ],
            name="fk_chunk_source_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "source_version_id", "parent_chunk_id"],
            [
                f"{APPLICATION_SCHEMA}.chunk.document_id",
                f"{APPLICATION_SCHEMA}.chunk.source_version_id",
                f"{APPLICATION_SCHEMA}.chunk.id",
            ],
            name="fk_chunk_parent_same_version",
            ondelete="CASCADE",
        ),
        Index("ix_chunk_source_version_id", "source_version_id"),
        Index(
            "ix_chunk_parent",
            "document_id",
            "source_version_id",
            "parent_chunk_id",
        ),
        Index("ix_chunk_full_text", "full_text", postgresql_using="gin"),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=sa.text("'{}'::text[]"),
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    full_text: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("statement_timestamp()"),
        nullable=False,
    )


class Conversation(TimestampMixin, Base):
    """Visitor conversation owned by a widget and browser session."""

    __tablename__ = "conversation"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(visitor_session_id)) > 0",
            name="ck_conversation_visitor_session",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_conversation_metadata_object",
        ),
        Index("ix_conversation_widget_id", "widget_id"),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    widget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.widget.id",
            name="fk_conversation_widget",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    visitor_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


class Message(Base):
    """User or assistant content in a conversation."""

    __tablename__ = "message"
    __table_args__ = (
        CheckConstraint("length(btrim(content)) > 0", name="ck_message_content"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_message_metadata_object"),
        Index("ix_message_conversation_id", "conversation_id"),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.conversation.id",
            name="fk_message_conversation",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(message_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("statement_timestamp()"),
        nullable=False,
    )


class RetrievalTrace(TimestampMixin, Base):
    """Minimal request-level trace; detailed pipeline stages are deferred."""

    __tablename__ = "retrieval_trace"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_retrieval_trace_metadata_object",
        ),
        Index("ix_retrieval_trace_conversation_id", "conversation_id"),
        Index("ix_retrieval_trace_terminal_state", "terminal_state"),
        {"schema": APPLICATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.conversation.id",
            name="fk_retrieval_trace_conversation",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    model_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    terminal_state: Mapped[RetrievalTerminalState] = mapped_column(
        retrieval_terminal_state_enum,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


class RetrievalTraceChunk(Base):
    """Ordered candidate link retained independently of chunk lifetime."""

    __tablename__ = "retrieval_trace_chunk"
    __table_args__ = (
        PrimaryKeyConstraint("trace_id", "chunk_id", name="pk_retrieval_trace_chunk"),
        UniqueConstraint("trace_id", "rank", name="uq_retrieval_trace_chunk_rank"),
        CheckConstraint("rank > 0", name="ck_retrieval_trace_chunk_rank_positive"),
        Index("ix_retrieval_trace_chunk_chunk_id", "chunk_id"),
        {"schema": APPLICATION_SCHEMA},
    )

    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.retrieval_trace.id",
            name="fk_retrieval_trace_chunk_trace",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{APPLICATION_SCHEMA}.chunk.id",
            name="fk_retrieval_trace_chunk_chunk",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
