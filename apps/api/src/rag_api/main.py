"""Health-only FastAPI application used to verify the development deployment path."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Public, non-sensitive deployment health metadata."""

    status: Literal["ok"] = "ok"
    service: Literal["rag-support-api"] = "rag-support-api"
    source_revision: str
    runtime_revision: str


app = FastAPI(
    title="RAG Support API health service",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report process health and traceable revision identifiers."""
    return HealthResponse(
        source_revision=os.getenv("APP_REVISION", "local"),
        runtime_revision=os.getenv("K_REVISION", "local"),
    )
