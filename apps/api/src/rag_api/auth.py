"""Supabase JWT verification and the single-role administrator dependency."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, cast
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWK
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from rag_api.database import database_session
from rag_api.db.repositories import AdminUserRepository

ALLOWED_JWT_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
AUTHENTICATED_ROLE: Literal["authenticated"] = "authenticated"
ADMIN_ROLE: Literal["admin"] = "admin"


class AuthConfigurationError(ValueError):
    """Raised when the server-side Supabase verification config is unsafe."""


class InvalidAccessToken(ValueError):
    """Raised for any token that fails cryptographic or claim verification."""


class TokenVerificationUnavailable(RuntimeError):
    """Raised when public signing keys cannot currently be refreshed."""


class AdminAuthenticationError(Exception):
    """Safe boundary error rendered by the FastAPI exception handler."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SupabaseAuthSettings:
    """Non-secret hosted Supabase verification configuration."""

    project_url: str
    audience: str = AUTHENTICATED_ROLE
    jwks_cache_ttl_seconds: int = 600

    @classmethod
    def from_environment(cls) -> SupabaseAuthSettings:
        raw_config = os.getenv("SUPABASE_AUTH_CONFIG")
        if raw_config is None:
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG is required.")
        try:
            payload = json.loads(raw_config)
        except json.JSONDecodeError as error:
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG must be a JSON object.") from error
        if not isinstance(payload, dict):
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG must be a JSON object.")
        allowed_fields = {"project_url", "audience", "jwks_cache_ttl_seconds"}
        if set(payload) - allowed_fields:
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG contains unsupported fields.")
        try:
            settings = cls(
                project_url=str(payload["project_url"]),
                audience=str(payload.get("audience", AUTHENTICATED_ROLE)),
                jwks_cache_ttl_seconds=int(payload.get("jwks_cache_ttl_seconds", 600)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AuthConfigurationError(
                "SUPABASE_AUTH_CONFIG is missing a valid project_url."
            ) from error
        settings.validate()
        return settings

    @property
    def issuer(self) -> str:
        return f"{self.project_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    def validate(self) -> None:
        parsed = urlparse(self.project_url)
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise AuthConfigurationError(
                "Supabase project_url must use HTTPS, except for local loopback testing."
            )
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AuthConfigurationError("Supabase project_url must be an origin URL.")
        if not self.audience.strip():
            raise AuthConfigurationError("Supabase audience must not be blank.")
        if not 60 <= self.jwks_cache_ttl_seconds <= 3600:
            raise AuthConfigurationError(
                "Supabase JWKS cache TTL must be between 60 and 3600 seconds."
            )


class JwksProvider(Protocol):
    """Resolve a public JSON Web Key by its token key ID."""

    async def get_key(self, key_id: str) -> dict[str, Any]: ...


class RemoteJwksProvider:
    """Fetch and cache Supabase public signing keys with unknown-key refresh."""

    def __init__(
        self,
        *,
        jwks_url: str,
        cache_ttl_seconds: int,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._jwks_url = jwks_url
        self._cache_ttl_seconds = cache_ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, key_id: str) -> dict[str, Any]:
        if time.monotonic() >= self._expires_at:
            await self._refresh()
        key = self._keys.get(key_id)
        if key is None:
            await self._refresh(force=True)
            key = self._keys.get(key_id)
        if key is None:
            raise InvalidAccessToken("The token signing key is unavailable.")
        return key

    async def _refresh(self, *, force: bool = False) -> None:
        async with self._lock:
            if not force and time.monotonic() < self._expires_at:
                return
            try:
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=self._timeout_seconds,
                ) as client:
                    response = await client.get(self._jwks_url)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise TokenVerificationUnavailable(
                    "The token signing keys could not be loaded."
                ) from error

            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                raise TokenVerificationUnavailable("The token signing keys are malformed.")

            keys: dict[str, dict[str, Any]] = {}
            for value in payload["keys"]:
                if not isinstance(value, dict):
                    continue
                key_id = value.get("kid")
                if isinstance(key_id, str) and key_id and value.get("kty") != "oct":
                    keys[key_id] = value
            if not keys:
                raise TokenVerificationUnavailable(
                    "No asymmetric token signing keys are available."
                )

            self._keys = keys
            self._expires_at = time.monotonic() + self._cache_ttl_seconds


@dataclass(frozen=True, slots=True)
class VerifiedSupabaseIdentity:
    """Authorization-safe claims extracted only after full JWT verification."""

    subject: uuid.UUID
    role: Literal["authenticated"] = AUTHENTICATED_ROLE


class AccessTokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedSupabaseIdentity: ...


class SupabaseJwtVerifier:
    """Verify Supabase JWT signature and required standard claims locally."""

    def __init__(
        self,
        settings: SupabaseAuthSettings,
        *,
        jwks_provider: JwksProvider | None = None,
    ) -> None:
        settings.validate()
        self._settings = settings
        self._jwks_provider = jwks_provider or RemoteJwksProvider(
            jwks_url=settings.jwks_url,
            cache_ttl_seconds=settings.jwks_cache_ttl_seconds,
        )

    async def verify(self, token: str) -> VerifiedSupabaseIdentity:
        try:
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            algorithm = header.get("alg")
            if (
                not isinstance(key_id, str)
                or not key_id
                or not isinstance(algorithm, str)
                or algorithm not in ALLOWED_JWT_ALGORITHMS
            ):
                raise InvalidAccessToken("The token header is invalid.")

            public_jwk = await self._jwks_provider.get_key(key_id)
            parsed_jwk = PyJWK.from_dict(public_jwk, algorithm=algorithm)
            if parsed_jwk.algorithm_name != algorithm:
                raise InvalidAccessToken("The token algorithm does not match its key.")

            claims = jwt.decode(
                token,
                key=parsed_jwk.key,
                algorithms=[algorithm],
                issuer=self._settings.issuer,
                audience=self._settings.audience,
                options={"require": ["iss", "aud", "sub", "exp"]},
            )
        except InvalidAccessToken:
            raise
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise InvalidAccessToken("The access token is invalid.") from error

        if claims.get("role") != AUTHENTICATED_ROLE or claims.get("is_anonymous") is True:
            raise AdminAuthenticationError(
                status_code=403,
                code="ADMIN_ACCESS_REQUIRED",
                message="Administrator access is required.",
            )
        try:
            subject = uuid.UUID(cast(str, claims["sub"]))
        except (ValueError, TypeError) as error:
            raise InvalidAccessToken("The access token subject is invalid.") from error
        return VerifiedSupabaseIdentity(subject=subject)


class AdminPrincipal(BaseModel):
    """Mapped administrator identity available to protected route handlers."""

    id: uuid.UUID
    supabase_user_id: uuid.UUID
    role: Literal["admin"] = ADMIN_ROLE


bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]
DatabaseSession = Annotated[AsyncSession, Depends(database_session)]


async def _verifier_for_request(request: Request) -> AccessTokenVerifier:
    injected = cast(
        AccessTokenVerifier | None,
        getattr(request.app.state, "auth_verifier", None),
    )
    if injected is not None:
        return injected

    lock = cast(asyncio.Lock, request.app.state.auth_verifier_lock)
    async with lock:
        verifier = cast(
            AccessTokenVerifier | None,
            getattr(request.app.state, "auth_verifier", None),
        )
        if verifier is None:
            verifier = SupabaseJwtVerifier(SupabaseAuthSettings.from_environment())
            request.app.state.auth_verifier = verifier
        return verifier


async def verified_supabase_identity(
    request: Request,
    credentials: BearerCredentials,
) -> VerifiedSupabaseIdentity:
    """Require one fully verified, non-anonymous Supabase bearer token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AdminAuthenticationError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="Authentication credentials could not be validated.",
        )
    try:
        verifier = await _verifier_for_request(request)
        return await verifier.verify(credentials.credentials)
    except AdminAuthenticationError:
        raise
    except (
        AuthConfigurationError,
        InvalidAccessToken,
        TokenVerificationUnavailable,
    ) as error:
        if isinstance(
            error,
            (AuthConfigurationError, TokenVerificationUnavailable),
        ):
            raise AdminAuthenticationError(
                status_code=503,
                code="AUTHENTICATION_UNAVAILABLE",
                message="Administrator authentication is temporarily unavailable.",
            ) from error
        raise AdminAuthenticationError(
            status_code=401,
            code="INVALID_ACCESS_TOKEN",
            message="Authentication credentials could not be validated.",
        ) from error


VerifiedIdentity = Annotated[
    VerifiedSupabaseIdentity,
    Depends(verified_supabase_identity),
]


async def current_admin(
    identity: VerifiedIdentity,
    session: DatabaseSession,
) -> AdminPrincipal:
    """Map the verified Supabase subject to exactly one local administrator."""
    admin_user = await AdminUserRepository(session).get_or_create_by_supabase_user_id(
        identity.subject
    )
    return AdminPrincipal(
        id=admin_user.id,
        supabase_user_id=admin_user.supabase_user_id,
    )


CurrentAdmin = Annotated[AdminPrincipal, Depends(current_admin)]
