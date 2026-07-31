"""Deterministic Supabase JWT verification and safe-boundary tests."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from rag_api.auth import (
    AdminAuthenticationError,
    InvalidAccessToken,
    RemoteJwksProvider,
    SupabaseAuthSettings,
    SupabaseJwtVerifier,
    TokenVerificationUnavailable,
    VerifiedSupabaseIdentity,
)
from rag_api.main import create_app

PROJECT_URL = "https://project-ref.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
AUDIENCE = "authenticated"
KEY_ID = "test-signing-key"


class StaticJwksProvider:
    """Resolve one deterministic public test key without network access."""

    def __init__(self, public_jwk: dict[str, Any]) -> None:
        self._public_jwk = public_jwk

    async def get_key(self, key_id: str) -> dict[str, Any]:
        if key_id != KEY_ID:
            raise InvalidAccessToken("Unknown test key.")
        return self._public_jwk


class CountingRemoteJwksProvider(RemoteJwksProvider):
    """Use deterministic keys while preserving production refresh coordination."""

    def __init__(self, public_jwk: dict[str, Any], clock: list[float]) -> None:
        super().__init__(
            jwks_url=f"{ISSUER}/.well-known/jwks.json",
            cache_ttl_seconds=600,
            clock=lambda: clock[0],
        )
        self._public_jwk = public_jwk
        self.fetch_count = 0

    async def _fetch_keys(self) -> dict[str, dict[str, Any]]:
        self.fetch_count += 1
        await asyncio.sleep(0)
        return {KEY_ID: self._public_jwk}


class UnavailableVerifier:
    async def verify(self, _token: str) -> VerifiedSupabaseIdentity:
        raise TokenVerificationUnavailable("provider detail must remain private")


@pytest.fixture
def signing_material() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    return private_key, public_jwk


def access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    subject: uuid.UUID | None = None,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_at: int | None = None,
    role: str = "authenticated",
    is_anonymous: bool = False,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": str(subject or uuid.uuid4()),
            "exp": expires_at if expires_at is not None else now + 300,
            "iat": now,
            "role": role,
            "is_anonymous": is_anonymous,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


def with_algorithm_header(token: str, algorithm: str) -> str:
    """Replace only the untrusted JWT header while retaining its forged signature."""
    _header, payload, signature = token.split(".")
    header = jwt.utils.base64url_encode(
        json.dumps(
            {"alg": algorithm, "kid": KEY_ID, "typ": "JWT"},
            separators=(",", ":"),
        ).encode()
    ).decode()
    return ".".join((header, payload, signature))


def verifier(public_jwk: dict[str, Any]) -> SupabaseJwtVerifier:
    return SupabaseJwtVerifier(
        SupabaseAuthSettings(project_url=PROJECT_URL),
        jwks_provider=StaticJwksProvider(public_jwk),
    )


@pytest.mark.anyio
async def test_valid_access_token_verifies_required_claims(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, public_jwk = signing_material
    subject = uuid.uuid4()

    identity = await verifier(public_jwk).verify(access_token(private_key, subject=subject))

    assert identity.subject == subject
    assert identity.role == "authenticated"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("issuer", "https://forged.example/auth/v1"),
        ("audience", "wrong-audience"),
        ("expires_at", 1),
    ],
)
async def test_issuer_audience_and_expiration_are_required(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
    override: str,
    value: str | int,
) -> None:
    private_key, public_jwk = signing_material

    with pytest.raises(InvalidAccessToken):
        await verifier(public_jwk).verify(access_token(private_key, **{override: value}))


@pytest.mark.anyio
async def test_forged_signature_is_rejected(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    _trusted_private_key, public_jwk = signing_material
    forged_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(InvalidAccessToken):
        await verifier(public_jwk).verify(access_token(forged_private_key))


@pytest.mark.anyio
async def test_unknown_key_refreshes_are_coalesced_and_rate_limited(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    _private_key, public_jwk = signing_material
    clock = [0.0]
    provider = CountingRemoteJwksProvider(public_jwk, clock)

    assert await provider.get_key(KEY_ID) == public_jwk
    assert provider.fetch_count == 1

    clock[0] = 60.0
    results = await asyncio.gather(
        *(provider.get_key(f"attacker-key-{index}") for index in range(20)),
        return_exceptions=True,
    )

    assert all(isinstance(result, InvalidAccessToken) for result in results)
    assert provider.fetch_count == 2

    clock[0] = 61.0
    with pytest.raises(InvalidAccessToken):
        await provider.get_key("another-attacker-key")
    assert provider.fetch_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("role", "is_anonymous"),
    [("anon", False), ("authenticated", True)],
)
async def test_verified_non_admin_sessions_are_forbidden(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
    role: str,
    is_anonymous: bool,
) -> None:
    private_key, public_jwk = signing_material

    with pytest.raises(AdminAuthenticationError) as raised:
        await verifier(public_jwk).verify(
            access_token(
                private_key,
                role=role,
                is_anonymous=is_anonymous,
            )
        )

    assert raised.value.status_code == 403
    assert raised.value.code == "ADMIN_ACCESS_REQUIRED"


@pytest.mark.anyio
async def test_absent_and_invalid_tokens_return_the_same_safe_401_shape(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, public_jwk = signing_material
    forged_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_app(auth_verifier=verifier(public_jwk))
    transport = httpx.ASGITransport(app=app)
    invalid_tokens = [
        access_token(private_key, expires_at=1),
        access_token(private_key, issuer="https://forged.example/auth/v1"),
        access_token(private_key, audience="wrong-audience"),
        access_token(forged_private_key),
        with_algorithm_header(access_token(private_key), "ES256"),
    ]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        absent = await client.get("/admin/auth-check")
        invalid_responses = [
            await client.get(
                "/admin/auth-check",
                headers={"Authorization": f"Bearer {invalid_token}"},
            )
            for invalid_token in invalid_tokens
        ]

    for response in (absent, *invalid_responses):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        payload = response.json()
        assert payload["contract_version"] == "v1"
        assert uuid.UUID(payload["request_id"])
        assert payload["error"] == {
            "code": ("AUTHENTICATION_REQUIRED" if response is absent else "INVALID_ACCESS_TOKEN"),
            "message": "Authentication credentials could not be validated.",
            "retryable": False,
            "details": [],
        }
        assert all(invalid_token not in response.text for invalid_token in invalid_tokens)
        assert "expired" not in response.text.lower()
        assert "signature" not in response.text.lower()
        assert str(private_key) not in response.text


@pytest.mark.anyio
async def test_verified_anonymous_session_returns_safe_403(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, public_jwk = signing_material
    app = create_app(auth_verifier=verifier(public_jwk))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/auth-check",
            headers={"Authorization": (f"Bearer {access_token(private_key, is_anonymous=True)}")},
        )

    assert response.status_code == 403
    assert "www-authenticate" not in response.headers
    assert response.json()["error"] == {
        "code": "ADMIN_ACCESS_REQUIRED",
        "message": "Administrator access is required.",
        "retryable": False,
        "details": [],
    }


@pytest.mark.anyio
async def test_jwks_outage_returns_safe_retryable_503() -> None:
    app = create_app(auth_verifier=UnavailableVerifier())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/auth-check",
            headers={"Authorization": "Bearer opaque-test-token"},
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "AUTHENTICATION_UNAVAILABLE",
        "message": "Administrator authentication is temporarily unavailable.",
        "retryable": True,
        "details": [],
    }
    assert "provider detail" not in response.text


def test_auth_config_rejects_non_https_remote_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_AUTH_CONFIG",
        '{"project_url":"http://project-ref.supabase.co"}',
    )

    with pytest.raises(ValueError, match="HTTPS"):
        SupabaseAuthSettings.from_environment()
