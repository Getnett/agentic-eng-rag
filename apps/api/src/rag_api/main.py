"""FastAPI application boundary for health and authenticated admin operations."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from rag_providers import (
    GenerationAdapter,
    GenerationDelta,
    GenerationRequest,
    ProviderAdapterError,
    ProviderOrchestrator,
    RequestBudget,
    VertexGenerationAdapter,
    VertexGenerationConfig,
)

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
VERTEX_SMOKE_PROMPT = """You answer only from the supplied support context.
Context: A customer can reset their password from Settings > Security > Reset password.
Question: Where can a customer reset their password?
Answer in one short sentence."""


@admin_router.get("/auth-check", response_model=AdminAuthCheckResponse)
async def admin_auth_check(admin: CurrentAdmin) -> AdminAuthCheckResponse:
    """Exercise only the authenticated administrator boundary."""
    return AdminAuthCheckResponse(
        admin_user_id=admin.id,
        supabase_user_id=admin.supabase_user_id,
    )


@admin_router.post("/ai/vertex-generation-smoke", response_model=None)
async def vertex_generation_smoke(
    request: Request,
    _admin: CurrentAdmin,
) -> StreamingResponse | JSONResponse:
    """Run one fixed, admin-only development prompt through Vertex streaming."""
    if os.getenv("APP_ENVIRONMENT") != "dev":
        raise HTTPException(status_code=404)

    factory = request.app.state.vertex_generation_adapter_factory
    try:
        adapter = factory()
    except ProviderAdapterError as error:
        return JSONResponse(
            status_code=503,
            content={
                "code": error.code.value,
                "message": str(error),
                "retryable": error.retryable,
            },
        )
    except ValueError:
        return JSONResponse(
            status_code=503,
            content={
                "code": "VERTEX_CONFIGURATION_UNAVAILABLE",
                "message": "Vertex generation is not configured.",
                "retryable": False,
            },
        )

    async def stream() -> AsyncIterator[str]:
        runtime = ProviderOrchestrator(generation=adapter)
        try:
            async for event in runtime.stream_generation(
                GenerationRequest(
                    prompt=VERTEX_SMOKE_PROMPT,
                    budget=RequestBudget(
                        timeout_seconds=30,
                        max_input_tokens=256,
                        max_output_tokens=96,
                    ),
                )
            ):
                if isinstance(event, GenerationDelta):
                    yield event.text
        except ProviderAdapterError as error:
            yield f"\n[provider-error:{error.code.value}]\n"
        finally:
            if isinstance(adapter, VertexGenerationAdapter):
                await adapter.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def create_app(
    *,
    auth_verifier: AccessTokenVerifier | None = None,
    database_session_factory: AsyncSessionFactory | None = None,
    vertex_generation_adapter_factory: Callable[[], GenerationAdapter] | None = None,
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
    application.state.vertex_generation_adapter_factory = (
        vertex_generation_adapter_factory
        if vertex_generation_adapter_factory is not None
        else lambda: VertexGenerationAdapter(VertexGenerationConfig.from_environment())
    )

    @application.exception_handler(AdminAuthenticationError)
    async def handle_admin_authentication_error(
        _request: Request,
        error: AdminAuthenticationError,
    ) -> JSONResponse:
        request_id = uuid.uuid4()
        if error.status_code in {401, 403, 503}:
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
