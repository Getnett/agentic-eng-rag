"""One-shot database migration runner for local and Cloud Run execution."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.interfaces import DBAPIConnection

APPLICATION_SCHEMA = "rag_app"
HEAD_REVISION = "0002_core_schema"
API_ROOT = Path(__file__).resolve().parents[2]


class MigrationConfigurationError(ValueError):
    """Raised when neither local nor Cloud SQL connection settings are complete."""


@dataclass(frozen=True)
class MigrationSettings:
    """Connection settings with credential-bearing values omitted from representations."""

    database_url: str | None = field(default=None, repr=False)
    instance_connection_name: str | None = None
    database_name: str | None = None
    database_user: str | None = None

    @classmethod
    def from_environment(cls) -> MigrationSettings:
        """Load either a local URL or the complete Cloud SQL IAM configuration."""
        settings = cls(
            database_url=os.getenv("DATABASE_URL"),
            instance_connection_name=os.getenv("INSTANCE_CONNECTION_NAME"),
            database_name=os.getenv("DB_NAME"),
            database_user=os.getenv("DB_USER"),
        )
        settings.validate()
        return settings

    @property
    def uses_cloud_sql(self) -> bool:
        """Return whether the settings select passwordless Cloud SQL connectivity."""
        return self.database_url is None

    def validate(self) -> None:
        """Require exactly one complete connection mode."""
        cloud_values = (
            self.instance_connection_name,
            self.database_name,
            self.database_user,
        )
        if self.database_url and any(cloud_values):
            raise MigrationConfigurationError(
                "Set DATABASE_URL or the Cloud SQL variables, not both."
            )
        if self.database_url:
            return
        if all(cloud_values):
            return
        raise MigrationConfigurationError(
            "Set DATABASE_URL, or set INSTANCE_CONNECTION_NAME, DB_NAME, and DB_USER."
        )


@dataclass(frozen=True)
class MigrationResult:
    """Non-sensitive migration metadata suitable for structured logs."""

    revision: str
    vector_version: str
    vector_probe: str

    def as_json(self) -> str:
        """Serialize deterministic completion evidence."""
        return json.dumps(
            {
                "event": "database_migration_complete",
                "revision": self.revision,
                "vector_probe": self.vector_probe,
                "vector_version": self.vector_version,
            },
            sort_keys=True,
        )


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


@contextmanager
def migration_engine(settings: MigrationSettings) -> Iterator[Engine]:
    """Create and dispose the selected SQLAlchemy engine and connector."""
    settings.validate()
    connector: Connector | None = None

    if settings.database_url is not None:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
    else:
        connector = Connector(refresh_strategy="LAZY")
        instance = cast(str, settings.instance_connection_name)
        database = cast(str, settings.database_name)
        user = cast(str, settings.database_user)

        def get_connection() -> DBAPIConnection:
            connection = connector.connect(
                instance,
                "pg8000",
                user=user,
                db=database,
                enable_iam_auth=True,
                ip_type=IPTypes.PRIVATE,
                application_name="rag-database-migrations",
            )
            return cast(DBAPIConnection, connection)

        engine = create_engine(
            "postgresql+pg8000://",
            creator=get_connection,
            pool_pre_ping=True,
        )

    try:
        yield engine
    finally:
        engine.dispose()
        if connector is not None:
            connector.close()


def _read_result(connection: Connection) -> MigrationResult:
    revision = connection.execute(
        text(f'SELECT version_num FROM "{APPLICATION_SCHEMA}".alembic_version')
    ).scalar_one()
    vector_version = connection.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one()
    vector_probe = connection.execute(text("SELECT '[1,2,3]'::vector::text")).scalar_one()
    return MigrationResult(
        revision=str(revision),
        vector_version=str(vector_version),
        vector_probe=str(vector_probe),
    )


def upgrade(settings: MigrationSettings) -> MigrationResult:
    """Upgrade to head transactionally and return safe verification metadata."""
    with migration_engine(settings) as engine:
        with engine.begin() as connection:
            command.upgrade(_alembic_config(connection), "head")
        with engine.connect() as connection:
            return _read_result(connection)


def downgrade(settings: MigrationSettings, revision: str = "base") -> None:
    """Downgrade to an explicit revision for local reversibility checks."""
    with migration_engine(settings) as engine:
        with engine.begin() as connection:
            command.downgrade(_alembic_config(connection), revision)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run application database migrations.")
    parser.add_argument(
        "action",
        choices=("upgrade", "downgrade"),
        nargs="?",
        default="upgrade",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested one-shot migration action."""
    args = _parser().parse_args(argv)
    try:
        settings = MigrationSettings.from_environment()
        if args.action == "downgrade":
            downgrade(settings)
            print(json.dumps({"event": "database_migration_downgraded"}, sort_keys=True))
        else:
            print(upgrade(settings).as_json())
    except MigrationConfigurationError as error:
        _parser().error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
