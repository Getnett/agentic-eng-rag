from __future__ import annotations

import uuid

import httpx
import pytest
from rag_api.auth import AdminPrincipal, current_admin
from rag_api.main import create_app
from rag_providers import FakeGenerationAdapter, ProviderAdapterError, ProviderErrorCode


def admin() -> AdminPrincipal:
    return AdminPrincipal(
        id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
        supabase_user_id=uuid.UUID("20000000-0000-0000-0000-000000000002"),
    )


@pytest.mark.anyio
async def test_admin_development_smoke_streams_through_generation_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "dev")
    app = create_app(
        vertex_generation_adapter_factory=lambda: FakeGenerationAdapter(
            response_prefix="Verified: "
        )
    )
    app.dependency_overrides[current_admin] = admin
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/ai/vertex-generation-smoke")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.text.startswith("Verified:")
    assert "reset their password" in response.text


@pytest.mark.anyio
async def test_smoke_endpoint_is_absent_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    app = create_app(vertex_generation_adapter_factory=lambda: FakeGenerationAdapter())
    app.dependency_overrides[current_admin] = admin
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/ai/vertex-generation-smoke")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_smoke_endpoint_returns_only_normalized_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "dev")
    app = create_app(
        vertex_generation_adapter_factory=lambda: FakeGenerationAdapter(
            failure=ProviderErrorCode.UNAVAILABLE
        )
    )
    app.dependency_overrides[current_admin] = admin
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/ai/vertex-generation-smoke")

    assert response.status_code == 200
    assert response.text == "\n[provider-error:unavailable]\n"
    assert "Deterministic fake provider failure" not in response.text


@pytest.mark.anyio
async def test_smoke_endpoint_normalizes_adapter_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "dev")

    def fail_adapter_initialization() -> FakeGenerationAdapter:
        raise ProviderAdapterError(
            code=ProviderErrorCode.INVALID_REQUEST,
            message="The Vertex generation request is not permitted.",
            provider_id="vertex-ai",
            model_id="gemini-test",
        )

    app = create_app(vertex_generation_adapter_factory=fail_adapter_initialization)
    app.dependency_overrides[current_admin] = admin
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/ai/vertex-generation-smoke")

    assert response.status_code == 503
    assert response.json() == {
        "code": "invalid_request",
        "message": "The Vertex generation request is not permitted.",
        "retryable": False,
    }


@pytest.mark.anyio
async def test_smoke_endpoint_requires_admin_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "dev")
    app = create_app(vertex_generation_adapter_factory=lambda: FakeGenerationAdapter())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/ai/vertex-generation-smoke")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
