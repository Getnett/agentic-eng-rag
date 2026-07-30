"""Create the grounded-chat core persistence schema.

Revision ID: 0002_core_schema
Revises: 0001_enable_pgvector
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0002_core_schema"
down_revision: str | Sequence[str] | None = "0001_enable_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rag_app"

source_type = postgresql.ENUM(
    "txt",
    "markdown",
    "pdf",
    "url",
    name="source_type",
    schema=SCHEMA,
    create_type=False,
)
source_version_status = postgresql.ENUM(
    "queued",
    "processing",
    "indexed",
    "failed",
    "superseded",
    name="source_version_status",
    schema=SCHEMA,
    create_type=False,
)
message_role = postgresql.ENUM(
    "user",
    "assistant",
    name="message_role",
    schema=SCHEMA,
    create_type=False,
)
retrieval_terminal_state = postgresql.ENUM(
    "answered",
    "abstained",
    "failed",
    name="retrieval_terminal_state",
    schema=SCHEMA,
    create_type=False,
)


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("statement_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    """Create the minimum source, chat, and trace persistence model."""
    bind = op.get_bind()
    source_type.create(bind, checkfirst=False)
    source_version_status.create(bind, checkfirst=False)
    message_role.create(bind, checkfirst=False)
    retrieval_terminal_state.create(bind, checkfirst=False)

    op.create_table(
        "widget",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("public_key_hash", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "allowed_origins",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "display_config",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "handoff_config",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(public_key_hash)) > 0",
            name="ck_widget_key_hash",
        ),
        sa.CheckConstraint(
            "array_position(allowed_origins, '') IS NULL",
            name="ck_widget_allowed_origins_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(display_config) = 'object'",
            name="ck_widget_display_config_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(handoff_config) = 'object'",
            name="ck_widget_handoff_config_object",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_widget"),
        sa.UniqueConstraint("public_key_hash", name="uq_widget_public_key_hash"),
        schema=SCHEMA,
    )

    op.create_table(
        "source_document",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_source_document_title",
        ),
        sa.CheckConstraint(
            "array_position(tags, '') IS NULL",
            name="ck_source_document_tags_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_document"),
        schema=SCHEMA,
    )

    op.create_table(
        "source_version",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            source_version_status,
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("raw_object_key", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_source_version_number_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_source_version_content_hash",
        ),
        sa.CheckConstraint(
            "raw_object_key IS NULL OR length(btrim(raw_object_key)) > 0",
            name="ck_source_version_raw_object_key",
        ),
        sa.CheckConstraint(
            "error IS NULL OR length(btrim(error)) > 0",
            name="ck_source_version_error",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_source_version_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            [f"{SCHEMA}.source_document.id"],
            name="fk_source_version_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_version"),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_source_version_document_number",
        ),
        sa.UniqueConstraint(
            "document_id",
            "id",
            name="uq_source_version_document_id",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_source_document_active_version",
        "source_document",
        "source_version",
        ["id", "active_version_id"],
        ["document_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_index(
        "ix_source_document_active_version_id",
        "source_document",
        ["active_version_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_source_version_document_status",
        "source_version",
        ["document_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_source_version_one_indexed",
        "source_version",
        ["document_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'indexed'"),
    )

    op.create_table(
        "chunk",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", VECTOR(), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column(
            "full_text",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, text)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("statement_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(text)) > 0", name="ck_chunk_text"),
        sa.CheckConstraint("token_count > 0", name="ck_chunk_token_count_positive"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_chunk_page_number_positive",
        ),
        sa.CheckConstraint(
            "heading IS NULL OR length(btrim(heading)) > 0",
            name="ck_chunk_heading",
        ),
        sa.CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_chunk_category",
        ),
        sa.CheckConstraint(
            "array_position(tags, '') IS NULL",
            name="ck_chunk_tags_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_chunk_metadata_object",
        ),
        sa.CheckConstraint(
            "(embedding IS NULL AND embedding_dimension IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_dimension > 0 "
            "AND vector_dims(embedding) = embedding_dimension)",
            name="ck_chunk_embedding_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "source_version_id"],
            [
                f"{SCHEMA}.source_version.document_id",
                f"{SCHEMA}.source_version.id",
            ],
            name="fk_chunk_source_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "source_version_id", "parent_chunk_id"],
            [
                f"{SCHEMA}.chunk.document_id",
                f"{SCHEMA}.chunk.source_version_id",
                f"{SCHEMA}.chunk.id",
            ],
            name="fk_chunk_parent_same_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunk"),
        sa.UniqueConstraint(
            "document_id",
            "source_version_id",
            "id",
            name="uq_chunk_document_version_id",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_chunk_source_version_id",
        "chunk",
        ["source_version_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_chunk_parent",
        "chunk",
        ["document_id", "source_version_id", "parent_chunk_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_chunk_full_text",
        "chunk",
        ["full_text"],
        schema=SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "conversation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("widget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_session_id", sa.String(length=255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(visitor_session_id)) > 0",
            name="ck_conversation_visitor_session",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_conversation_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["widget_id"],
            [f"{SCHEMA}.widget.id"],
            name="fk_conversation_widget",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_widget_id",
        "conversation",
        ["widget_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("statement_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(content)) > 0", name="ck_message_content"),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_message_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{SCHEMA}.conversation.id"],
            name="fk_message_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_message_conversation_id",
        "message",
        ["conversation_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "retrieval_trace",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("terminal_state", retrieval_terminal_state, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_retrieval_trace_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{SCHEMA}.conversation.id"],
            name="fk_retrieval_trace_conversation",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_trace"),
        sa.UniqueConstraint("request_id", name="uq_retrieval_trace_request_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_retrieval_trace_conversation_id",
        "retrieval_trace",
        ["conversation_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_retrieval_trace_terminal_state",
        "retrieval_trace",
        ["terminal_state"],
        schema=SCHEMA,
    )

    op.create_table(
        "retrieval_trace_chunk",
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rank > 0",
            name="ck_retrieval_trace_chunk_rank_positive",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            [f"{SCHEMA}.retrieval_trace.id"],
            name="fk_retrieval_trace_chunk_trace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            [f"{SCHEMA}.chunk.id"],
            name="fk_retrieval_trace_chunk_chunk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "trace_id",
            "chunk_id",
            name="pk_retrieval_trace_chunk",
        ),
        sa.UniqueConstraint(
            "trace_id",
            "rank",
            name="uq_retrieval_trace_chunk_rank",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_retrieval_trace_chunk_chunk_id",
        "retrieval_trace_chunk",
        ["chunk_id"],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.enforce_source_version_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF OLD.status = NEW.status THEN
            RETURN NEW;
          END IF;
          IF (OLD.status = 'queued' AND NEW.status IN ('processing', 'failed'))
             OR (OLD.status = 'processing' AND NEW.status IN ('indexed', 'failed'))
             OR (OLD.status = 'indexed' AND NEW.status = 'superseded') THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'illegal source version transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_source_version_transition
        BEFORE UPDATE OF status ON {SCHEMA}.source_version
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.enforce_source_version_transition()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$
        """
    )
    for table in (
        "widget",
        "source_document",
        "source_version",
        "conversation",
        "retrieval_trace",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {SCHEMA}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.set_updated_at()
            """
        )


def downgrade() -> None:
    """Remove core tables while preserving the pgvector baseline revision."""
    for table in (
        "widget",
        "source_document",
        "source_version",
        "conversation",
        "retrieval_trace",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.set_updated_at()")
    op.execute(f"DROP TRIGGER IF EXISTS trg_source_version_transition ON {SCHEMA}.source_version")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.enforce_source_version_transition()")

    op.drop_constraint(
        "fk_source_document_active_version",
        "source_document",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("retrieval_trace_chunk", schema=SCHEMA)
    op.drop_table("retrieval_trace", schema=SCHEMA)
    op.drop_table("message", schema=SCHEMA)
    op.drop_table("conversation", schema=SCHEMA)
    op.drop_table("chunk", schema=SCHEMA)
    op.drop_table("source_version", schema=SCHEMA)
    op.drop_table("source_document", schema=SCHEMA)
    op.drop_table("widget", schema=SCHEMA)

    bind = op.get_bind()
    retrieval_terminal_state.drop(bind, checkfirst=False)
    message_role.drop(bind, checkfirst=False)
    source_version_status.drop(bind, checkfirst=False)
    source_type.drop(bind, checkfirst=False)
