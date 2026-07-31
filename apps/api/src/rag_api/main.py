"""FastAPI application boundary for health and authenticated admin operations."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rag_api.auth import (
    AccessTokenVerifier,
    AdminAuthenticationError,
    CurrentAdmin,
)
from rag_api.database import AsyncSessionFactory, DatabaseRuntime


class HealthResponse(BaseModel):
    """Public, non-sensitive deployment health metadata."""

    status: Literal["ok"] = "ok"
    service: Literal["rag-support-api"] = "rag-support-api"
    source_revision: str
    runtime_revision: str


class AdminAuthCheckResponse(BaseModel):
    """Non-secret proof that a verified subject reached the admin boundary."""

    admin_user_id: uuid.UUID
    supabase_user_id: uuid.UUID
    role: Literal["admin"] = "admin"


class PublicError(BaseModel):
    code: Literal["AUTHENTICATION_REQUIRED", "SERVICE_UNAVAILABLE"]
    message: str
    retryable: bool = False


class PublicErrorEnvelope(BaseModel):
    contract_version: Literal["v1"] = "v1"
    request_id: uuid.UUID
    error: PublicError


class AdminErrorDetail(BaseModel):
    field: str | None
    reason: str


class AdminError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: list[AdminErrorDetail]


class AdminErrorEnvelope(BaseModel):
    contract_version: Literal["v1"] = "v1"
    request_id: uuid.UUID
    error: AdminError


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/auth-check", response_model=AdminAuthCheckResponse)
async def admin_auth_check(admin: CurrentAdmin) -> AdminAuthCheckResponse:
    """Exercise only the authenticated administrator boundary."""
    return AdminAuthCheckResponse(
        admin_user_id=admin.id,
        supabase_user_id=admin.supabase_user_id,
    )


def create_app(
    *,
    auth_verifier: AccessTokenVerifier | None = None,
    database_session_factory: AsyncSessionFactory | None = None,
) -> FastAPI:
    """Create an app with optional deterministic auth/database test seams."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        runtime = getattr(application.state, "database_runtime", None)
        if isinstance(runtime, DatabaseRuntime):
            await runtime.close()

    application = FastAPI(
        title="RAG Support API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.auth_verifier = auth_verifier
    application.state.auth_verifier_lock = asyncio.Lock()
    application.state.database_runtime = None
    application.state.database_runtime_lock = asyncio.Lock()
    application.state.database_session_factory = database_session_factory

    @application.exception_handler(AdminAuthenticationError)
    async def handle_admin_authentication_error(
        _request: Request,
        error: AdminAuthenticationError,
    ) -> JSONResponse:
        request_id = uuid.uuid4()
        if error.status_code in {401, 503}:
            envelope: PublicErrorEnvelope | AdminErrorEnvelope = PublicErrorEnvelope(
                request_id=request_id,
                error=PublicError(
                    code=(
                        "SERVICE_UNAVAILABLE"
                        if error.status_code == 503
                        else "AUTHENTICATION_REQUIRED"
                    ),
                    message=error.message,
                    retryable=error.status_code == 503,
                ),
            )
        else:
            envelope = AdminErrorEnvelope(
                request_id=request_id,
                error=AdminError(
                    code=error.code,
                    message=error.message,
                    details=[],
                ),
            )
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        return JSONResponse(
            status_code=error.status_code,
            content=envelope.model_dump(mode="json"),
            headers=headers,
        )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Report process health and traceable revision identifiers."""
        return HealthResponse(
            source_revision=os.getenv("APP_REVISION", "local"),
            runtime_revision=os.getenv("K_REVISION", "local"),
        )

    application.include_router(admin_router)
    return application


app = create_app()
