"""Supabase JWT verification and the single-role administrator dependency."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, cast
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWK
from jwt.exceptions import InvalidKeyError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from rag_api.database import database_session
from rag_api.db.repositories import AdminUserRepository

ALLOWED_JWT_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
AUTHENTICATED_ROLE: Literal["authenticated"] = "authenticated"
ADMIN_ROLE: Literal["admin"] = "admin"
JWKS_REFRESH_COOLDOWN_SECONDS = 60.0


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
        project_url = payload.get("project_url")
        if not isinstance(project_url, str):
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG is missing a valid project_url.")
        audience = payload.get("audience", AUTHENTICATED_ROLE)
        if not isinstance(audience, str):
            raise AuthConfigurationError("SUPABASE_AUTH_CONFIG audience must be a nonblank string.")
        try:
            settings = cls(
                project_url=project_url,
                audience=audience,
                jwks_cache_ttl_seconds=int(payload.get("jwks_cache_ttl_seconds", 600)),
            )
        except (TypeError, ValueError) as error:
            raise AuthConfigurationError(
                "SUPABASE_AUTH_CONFIG contains an invalid JWKS cache TTL."
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._jwks_url = jwks_url
        self._cache_ttl_seconds = cache_ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0
        self._refresh_generation = 0
        self._next_refresh_attempt_at = 0.0
        self._refresh_failed = False
        self._lock = asyncio.Lock()

    async def get_key(self, key_id: str) -> dict[str, Any]:
        if self._clock() >= self._expires_at:
            await self._refresh()
        key = self._keys.get(key_id)
        if key is None:
            await self._refresh_for_unknown_key(
                key_id=key_id,
                observed_generation=self._refresh_generation,
            )
            key = self._keys.get(key_id)
        if key is None:
            raise InvalidAccessToken("The token signing key is unavailable.")
        return key

    async def _refresh(self) -> None:
        async with self._lock:
            if self._clock() < self._expires_at:
                return
            await self._refresh_keys_with_cooldown()

    async def _refresh_for_unknown_key(
        self,
        *,
        key_id: str,
        observed_generation: int,
    ) -> None:
        async with self._lock:
            if key_id in self._keys or self._refresh_generation != observed_generation:
                return

            now = self._clock()
            if now < self._next_refresh_attempt_at:
                if self._refresh_failed:
                    self._raise_cached_refresh_failure()
                return

            await self._refresh_keys_with_cooldown()

    async def _refresh_keys_with_cooldown(self) -> None:
        now = self._clock()
        if now < self._next_refresh_attempt_at:
            if self._refresh_failed:
                self._raise_cached_refresh_failure()
            return

        self._next_refresh_attempt_at = now + JWKS_REFRESH_COOLDOWN_SECONDS
        try:
            keys = await self._fetch_keys()
        except TokenVerificationUnavailable:
            self._refresh_failed = True
            raise
        self._install_keys(keys)

    @staticmethod
    def _raise_cached_refresh_failure() -> None:
        raise TokenVerificationUnavailable("The token signing keys could not be loaded.")

    async def _fetch_keys(self) -> dict[str, dict[str, Any]]:
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

        return self._validated_signing_keys(payload)

    @staticmethod
    def _validated_signing_keys(payload: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise TokenVerificationUnavailable("The token signing keys are malformed.")

        keys: dict[str, dict[str, Any]] = {}
        for value in payload["keys"]:
            if not isinstance(value, dict):
                continue
            key_id = value.get("kid")
            algorithm = value.get("alg")
            key_type = value.get("kty")
            public_key_use = value.get("use")
            key_operations = value.get("key_ops")
            if (
                not isinstance(key_id, str)
                or not key_id
                or not isinstance(algorithm, str)
                or algorithm not in ALLOWED_JWT_ALGORITHMS
                or not isinstance(key_type, str)
                or key_type == "oct"
                or (public_key_use is not None and public_key_use != "sig")
                or (
                    key_operations is not None
                    and (not isinstance(key_operations, list) or "verify" not in key_operations)
                )
            ):
                continue
            try:
                PyJWK.from_dict(value, algorithm=algorithm)
            except (InvalidTokenError, InvalidKeyError, KeyError, TypeError, ValueError):
                continue
            keys[key_id] = value
        if not keys:
            raise TokenVerificationUnavailable("No asymmetric token signing keys are available.")
        return keys

    def _install_keys(self, keys: dict[str, dict[str, Any]]) -> None:
        now = self._clock()
        self._keys = keys
        self._expires_at = now + self._cache_ttl_seconds
        self._refresh_generation += 1
        self._next_refresh_attempt_at = now + JWKS_REFRESH_COOLDOWN_SECONDS
        self._refresh_failed = False


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
            jwk_algorithm = public_jwk.get("alg")
            if (
                not isinstance(jwk_algorithm, str)
                or jwk_algorithm not in ALLOWED_JWT_ALGORITHMS
                or jwk_algorithm != algorithm
            ):
                raise InvalidAccessToken("The token algorithm does not match its key.")
            parsed_jwk = PyJWK.from_dict(public_jwk, algorithm=jwk_algorithm)

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
        except (InvalidTokenError, InvalidKeyError, KeyError, TypeError, ValueError) as error:
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
