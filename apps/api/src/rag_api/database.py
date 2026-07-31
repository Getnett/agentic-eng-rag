"""Async application database runtime for local and Cloud SQL connections."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import cast

from fastapi import Request
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

AsyncSessionFactory = Callable[[], AsyncSession]


class DatabaseConfigurationError(ValueError):
    """Raised when application database connection settings are incomplete."""


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Credential-bearing local URLs are excluded from representations."""

    database_url: str | None = field(default=None, repr=False)
    instance_connection_name: str | None = None
    database_name: str | None = None
    database_user: str | None = None

    @classmethod
    def from_environment(cls) -> DatabaseSettings:
        settings = cls(
            database_url=os.getenv("DATABASE_URL"),
            instance_connection_name=os.getenv("INSTANCE_CONNECTION_NAME"),
            database_name=os.getenv("DB_NAME"),
            database_user=os.getenv("DB_USER"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        cloud_values = (
            self.instance_connection_name,
            self.database_name,
            self.database_user,
        )
        if self.database_url and any(cloud_values):
            raise DatabaseConfigurationError(
                "Set DATABASE_URL or the Cloud SQL variables, not both."
            )
        if self.database_url is not None:
            if not self.database_url.startswith(("postgresql+asyncpg://", "postgresql://")):
                raise DatabaseConfigurationError(
                    "DATABASE_URL must select PostgreSQL with the asyncpg driver."
                )
            return
        if all(cloud_values):
            return
        raise DatabaseConfigurationError(
            "Set DATABASE_URL, or set INSTANCE_CONNECTION_NAME, DB_NAME, and DB_USER."
        )


class DatabaseRuntime:
    """Own the async SQLAlchemy engine and optional Cloud SQL connector."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        connector: Connector | None,
    ) -> None:
        self.engine = engine
        self.connector = connector
        self.session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @classmethod
    async def create(cls, settings: DatabaseSettings) -> DatabaseRuntime:
        settings.validate()
        if settings.database_url is not None:
            database_url = settings.database_url
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace(
                    "postgresql://",
                    "postgresql+asyncpg://",
                    1,
                )
            engine = create_async_engine(database_url, pool_pre_ping=True)
            return cls(engine=engine, connector=None)

        connector = Connector(
            loop=asyncio.get_running_loop(),
            refresh_strategy="LAZY",
        )
        instance = cast(str, settings.instance_connection_name)
        database = cast(str, settings.database_name)
        user = cast(str, settings.database_user)

        async def connect() -> AsyncConnection:
            connection = await connector.connect_async(
                instance,
                "asyncpg",
                user=user,
                db=database,
                enable_iam_auth=True,
                ip_type=IPTypes.PRIVATE,
            )
            return cast(AsyncConnection, connection)

        engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=connect,
            pool_pre_ping=True,
        )
        return cls(engine=engine, connector=connector)

    async def close(self) -> None:
        await self.engine.dispose()
        if self.connector is not None:
            await self.connector.close_async()


async def _runtime_for_request(request: Request) -> DatabaseRuntime:
    runtime = getattr(request.app.state, "database_runtime", None)
    if isinstance(runtime, DatabaseRuntime):
        return runtime

    lock = cast(asyncio.Lock, request.app.state.database_runtime_lock)
    async with lock:
        runtime = getattr(request.app.state, "database_runtime", None)
        if isinstance(runtime, DatabaseRuntime):
            return runtime
        runtime = await DatabaseRuntime.create(DatabaseSettings.from_environment())
        request.app.state.database_runtime = runtime
        return runtime


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one caller-owned transaction for a request."""
    injected_factory = cast(
        AsyncSessionFactory | None,
        getattr(request.app.state, "database_session_factory", None),
    )
    factory = injected_factory
    if factory is None:
        factory = (await _runtime_for_request(request)).session_factory

    async with factory() as session:
        async with session.begin():
            yield session
