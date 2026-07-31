"""Database-backed administrator subject mapping at the FastAPI boundary."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from rag_api.auth import InvalidAccessToken, SupabaseAuthSettings, SupabaseJwtVerifier
from rag_api.main import create_app
from rag_api.migrations import MigrationSettings, upgrade
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

KEY_ID = "integration-key"
PROJECT_URL = "https://project-ref.supabase.co"


class StaticJwksProvider:
    def __init__(self, public_jwk: dict[str, Any]) -> None:
        self._public_jwk = public_jwk

    async def get_key(self, key_id: str) -> dict[str, Any]:
        if key_id != KEY_ID:
            raise InvalidAccessToken("Unknown test key.")
        return self._public_jwk


@pytest.mark.anyio
async def test_verified_subject_is_mapped_once_and_reaches_protected_stub(
    postgres_database_url: str,
) -> None:
    upgrade(MigrationSettings(database_url=postgres_database_url))
    async_url = postgres_database_url.replace(
        "postgresql+pg8000://",
        "postgresql+asyncpg://",
        1,
    )
    engine = create_async_engine(async_url)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    verifier = SupabaseJwtVerifier(
        SupabaseAuthSettings(project_url=PROJECT_URL),
        jwks_provider=StaticJwksProvider(public_jwk),
    )
    subject = uuid.uuid4()
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": f"{PROJECT_URL}/auth/v1",
            "aud": "authenticated",
            "sub": str(subject),
            "exp": now + 300,
            "iat": now,
            "role": "authenticated",
            "is_anonymous": False,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )

    async with engine.connect() as connection:
        outer_transaction = await connection.begin()

        def session_factory() -> AsyncSession:
            return AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

        app = create_app(
            auth_verifier=verifier,
            database_session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.get(
                "/admin/auth-check",
                headers={"Authorization": f"Bearer {token}"},
            )
            second = await client.get(
                "/admin/auth-check",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert first.json()["supabase_user_id"] == str(subject)
        assert first.json()["role"] == "admin"
        assert set(first.json()) == {"admin_user_id", "supabase_user_id", "role"}

        mapping_count = await connection.scalar(
            text("SELECT count(*) FROM rag_app.admin_user WHERE supabase_user_id = :subject"),
            {"subject": subject},
        )
        role = await connection.scalar(
            text("SELECT role FROM rag_app.admin_user WHERE supabase_user_id = :subject"),
            {"subject": subject},
        )
        assert mapping_count == 1
        assert role == "admin"
        await outer_transaction.rollback()

    await engine.dispose()
