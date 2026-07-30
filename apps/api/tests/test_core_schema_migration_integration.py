from __future__ import annotations

from rag_api.migrations import (
    APPLICATION_SCHEMA,
    HEAD_REVISION,
    MigrationSettings,
    downgrade,
    upgrade,
)
from sqlalchemy import create_engine, text

EXPECTED_TABLES = {
    "alembic_version",
    "chunk",
    "conversation",
    "message",
    "retrieval_trace",
    "retrieval_trace_chunk",
    "source_document",
    "source_version",
    "widget",
}
EXPECTED_ENUM_VALUES = {
    "message_role": ["user", "assistant"],
    "retrieval_terminal_state": ["answered", "abstained", "failed"],
    "source_type": ["txt", "markdown", "pdf", "url"],
    "source_version_status": [
        "queued",
        "processing",
        "indexed",
        "failed",
        "superseded",
    ],
}
REQUIRED_CONSTRAINTS = {
    "ck_chunk_embedding_dimension",
    "ck_chunk_heading",
    "ck_chunk_metadata_object",
    "ck_chunk_page_number_positive",
    "ck_chunk_tags_nonempty",
    "ck_chunk_text",
    "ck_chunk_token_count_positive",
    "ck_conversation_metadata_object",
    "ck_conversation_visitor_session",
    "ck_message_content",
    "ck_message_metadata_object",
    "ck_retrieval_trace_chunk_rank_positive",
    "ck_retrieval_trace_metadata_object",
    "ck_source_document_location",
    "ck_source_document_tags_nonempty",
    "ck_source_document_title",
    "ck_source_version_content_hash",
    "ck_source_version_error_matches_status",
    "ck_source_version_metadata_object",
    "ck_source_version_number_positive",
    "fk_chunk_parent_same_version",
    "fk_chunk_source_version",
    "fk_retrieval_trace_chunk_chunk",
    "fk_source_document_active_version",
    "uq_retrieval_trace_request_id",
    "uq_source_version_document_number",
}
REQUIRED_INDEXES = {
    "ix_chunk_full_text",
    "ix_chunk_parent",
    "ix_chunk_source_version_id",
    "ix_conversation_widget_id",
    "ix_message_conversation_id",
    "ix_retrieval_trace_chunk_chunk_id",
    "ix_retrieval_trace_conversation_id",
    "ix_retrieval_trace_terminal_state",
    "ix_source_document_active_version_id",
    "ix_source_version_document_status",
    "uq_source_version_one_indexed",
}


def test_core_schema_upgrade_downgrade_and_catalog_contract(
    postgres_database_url: str,
) -> None:
    settings = MigrationSettings(database_url=postgres_database_url)
    result = upgrade(settings)
    engine = create_engine(postgres_database_url)

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
                ),
                {"schema": APPLICATION_SCHEMA},
            )
            .scalars()
            .all()
        )
        enum_rows = connection.execute(
            text(
                "SELECT type.typname, enum.enumlabel "
                "FROM pg_type AS type "
                "JOIN pg_enum AS enum ON enum.enumtypid = type.oid "
                "JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
                "WHERE namespace.nspname = :schema "
                "ORDER BY type.typname, enum.enumsortorder"
            ),
            {"schema": APPLICATION_SCHEMA},
        ).all()
        enum_values: dict[str, list[str]] = {}
        for enum_name, enum_value in enum_rows:
            enum_values.setdefault(str(enum_name), []).append(str(enum_value))
        constraints = set(
            connection.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE constraint_schema = :schema"
                ),
                {"schema": APPLICATION_SCHEMA},
            )
            .scalars()
            .all()
        )
        index_rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :schema"),
            {"schema": APPLICATION_SCHEMA},
        ).all()
        indexes = {str(name) for name, _definition in index_rows}
        index_definitions = {str(name): str(definition) for name, definition in index_rows}
        full_text_generation = connection.execute(
            text(
                "SELECT is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'chunk' "
                "AND column_name = 'full_text'"
            ),
            {"schema": APPLICATION_SCHEMA},
        ).one()
        triggers = set(
            connection.execute(
                text(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE trigger_schema = :schema"
                ),
                {"schema": APPLICATION_SCHEMA},
            )
            .scalars()
            .all()
        )
        vector_probe = connection.execute(text("SELECT '[1,2,3]'::vector::text")).scalar_one()

    assert result.revision == HEAD_REVISION
    assert EXPECTED_TABLES <= tables
    assert enum_values == EXPECTED_ENUM_VALUES
    assert REQUIRED_CONSTRAINTS <= constraints
    assert REQUIRED_INDEXES <= indexes
    assert full_text_generation.is_generated == "ALWAYS"
    assert "'simple'::regconfig" in full_text_generation.generation_expression
    assert "USING gin" in index_definitions["ix_chunk_full_text"]
    for index_name in REQUIRED_INDEXES - {"ix_chunk_full_text"}:
        assert "USING btree" in index_definitions[index_name]
    assert all(
        "USING hnsw" not in definition and "USING ivfflat" not in definition
        for definition in index_definitions.values()
    )
    assert "trg_source_version_transition" in triggers
    assert vector_probe == "[1,2,3]"

    downgrade(settings, "0001_enable_pgvector")
    with engine.connect() as connection:
        remaining_tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
                ),
                {"schema": APPLICATION_SCHEMA},
            )
            .scalars()
            .all()
        )
        extension_count = connection.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
    assert remaining_tables == {"alembic_version"}
    assert extension_count == 1

    restored = upgrade(settings)
    assert restored.revision == HEAD_REVISION
    engine.dispose()
