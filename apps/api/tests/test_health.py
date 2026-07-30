from __future__ import annotations

import httpx
import pytest
from rag_api.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_endpoint_reports_safe_revision_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_REVISION", "a" * 40)
    monkeypatch.setenv("K_REVISION", "rag-dev-api-abc123")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "rag-support-api",
        "source_revision": "a" * 40,
        "runtime_revision": "rag-dev-api-abc123",
    }


@pytest.mark.anyio
async def test_health_image_exposes_no_product_or_documentation_routes() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.get("/docs")).status_code == 404
