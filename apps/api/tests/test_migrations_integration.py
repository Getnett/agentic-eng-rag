from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pg8000.dbapi
from rag_api.migrations import (
    APPLICATION_SCHEMA,
    HEAD_REVISION,
    MigrationSettings,
    downgrade,
    upgrade,
)
from sqlalchemy import create_engine, text

PGVECTOR_IMAGE = (
    "pgvector/pgvector:0.8.1-pg16@"
    "sha256:33198da2828a14c30348d2ccb4750833d5ed9a44c88d840a0e523d7417120337"
)


def _docker(*args: str) -> str:
    result = subprocess.run(
        ("docker", *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@contextmanager
def postgres_url() -> Iterator[str]:
    container_id = _docker(
        "run",
        "--detach",
        "--rm",
        "--env",
        "POSTGRES_PASSWORD=migration-test",
        "--env",
        "POSTGRES_DB=migration_test",
        "--publish",
        "127.0.0.1::5432",
        PGVECTOR_IMAGE,
    )
    try:
        port_output = _docker("port", container_id, "5432/tcp")
        port = int(port_output.rsplit(":", maxsplit=1)[1])
        deadline = time.monotonic() + 30
        while True:
            try:
                connection = pg8000.dbapi.connect(
                    host="127.0.0.1",
                    port=port,
                    database="migration_test",
                    user="postgres",
                    password="migration-test",
                    timeout=1,
                )
                connection.close()
                break
            except (pg8000.dbapi.Error, OSError):
                if time.monotonic() >= deadline:
                    logs = _docker("logs", container_id)
                    raise RuntimeError(f"PostgreSQL did not become ready:\n{logs}") from None
                time.sleep(0.25)
        yield (f"postgresql+pg8000://postgres:migration-test@127.0.0.1:{port}/migration_test")
    finally:
        _docker("rm", "--force", container_id)


def test_baseline_upgrade_is_idempotent_and_reversible() -> None:
    with postgres_url() as database_url:
        settings = MigrationSettings(database_url=database_url)

        first_result = upgrade(settings)
        engine = create_engine(database_url)
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
