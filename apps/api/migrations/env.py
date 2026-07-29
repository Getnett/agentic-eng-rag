"""Alembic environment for the application-owned PostgreSQL schema."""

from __future__ import annotations

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection

APPLICATION_SCHEMA = "rag_app"


def run_migrations() -> None:
    """Run migrations using the connection supplied by the one-shot runner."""
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("Migrations require a caller-managed SQLAlchemy connection.")

    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{APPLICATION_SCHEMA}"'))
    context.configure(
        connection=connection,
        target_metadata=None,
        transactional_ddl=True,
        version_table="alembic_version",
        version_table_schema=APPLICATION_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


run_migrations()
