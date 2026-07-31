"""Shared PostgreSQL fixture for migration and repository integration tests."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

import pg8000.dbapi
import pytest

PGVECTOR_IMAGE = (
    "pgvector/pgvector:0.8.1-pg16@"
    "sha256:33198da2828a14c30348d2ccb4750833d5ed9a44c88d840a0e523d7417120337"
)


def docker(*args: str) -> str:
    result = subprocess.run(
        ("docker", *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def postgres_database_url() -> Iterator[str]:
    """Provide one isolated pgvector PostgreSQL database for the test session."""
    container_id = docker(
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
        port_output = docker("port", container_id, "5432/tcp")
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
                    logs = docker("logs", container_id)
                    raise RuntimeError(f"PostgreSQL did not become ready:\n{logs}") from None
                time.sleep(0.25)
        yield f"postgresql+pg8000://postgres:migration-test@127.0.0.1:{port}/migration_test"
    finally:
        docker("rm", "--force", container_id)


@pytest.fixture
def anyio_backend() -> str:
    """Run async repository tests on the asyncio backend only."""
    return "asyncio"
