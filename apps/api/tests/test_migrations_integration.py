from __future__ import annotations

from rag_api.migrations import (
    APPLICATION_SCHEMA,
    HEAD_REVISION,
    MigrationSettings,
    downgrade,
    upgrade,
)
from sqlalchemy import create_engine, text


def test_baseline_upgrade_is_idempotent_and_reversible(
    postgres_database_url: str,
) -> None:
    settings = MigrationSettings(database_url=postgres_database_url)

    first_result = upgrade(settings)
    engine = create_engine(postgres_database_url)
    with engine.connect() as connection:
        first_extension_oid = connection.execute(
            text("SELECT oid FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        first_version_rows = (
            connection.execute(
                text(f'SELECT version_num FROM "{APPLICATION_SCHEMA}".alembic_version')
            )
            .scalars()
            .all()
        )
        schema_exists = connection.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"
                ")"
            ),
            {"schema": APPLICATION_SCHEMA},
        ).scalar_one()

    second_result = upgrade(settings)
    with engine.connect() as connection:
        second_extension_oid = connection.execute(
            text("SELECT oid FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        second_version_rows = (
            connection.execute(
                text(f'SELECT version_num FROM "{APPLICATION_SCHEMA}".alembic_version')
            )
            .scalars()
            .all()
        )

    assert schema_exists
    assert first_result.revision == HEAD_REVISION
    assert first_result.vector_probe == "[1,2,3]"
    assert first_result == second_result
    assert first_version_rows == [HEAD_REVISION]
    assert second_version_rows == first_version_rows
    assert second_extension_oid == first_extension_oid

    downgrade(settings)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text(f'SELECT count(*) FROM "{APPLICATION_SCHEMA}".alembic_version')
            ).scalar_one()
            == 0
        )

    restored_result = upgrade(settings)
    assert restored_result.revision == HEAD_REVISION
    engine.dispose()


def test_upgrade_grants_only_required_admin_mapping_access(
    postgres_database_url: str,
) -> None:
    role = "por36-api"
    engine = create_engine(postgres_database_url)
    with engine.begin() as connection:
        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))

    try:
        upgrade(
            MigrationSettings(
                database_url=postgres_database_url,
                application_database_user=role,
            )
        )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT has_schema_privilege(:role, 'rag_app', 'USAGE')"),
                {"role": role},
            ).scalar_one()
            assert connection.execute(
                text("SELECT has_table_privilege(:role, 'rag_app.admin_user', 'SELECT,INSERT')"),
                {"role": role},
            ).scalar_one()
            assert not connection.execute(
                text("SELECT has_table_privilege(:role, 'rag_app.source_document', 'INSERT')"),
                {"role": role},
            ).scalar_one()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))
        engine.dispose()
