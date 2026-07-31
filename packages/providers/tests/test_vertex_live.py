from __future__ import annotations

import os

import pytest
from rag_providers import (
    GenerationRequest,
    ProviderOrchestrator,
    RequestBudget,
    VertexGenerationAdapter,
    VertexGenerationConfig,
)


@pytest.mark.anyio
@pytest.mark.skipif(
    os.getenv("RUN_VERTEX_INTEGRATION") != "1",
    reason="Real Vertex calls require explicit RUN_VERTEX_INTEGRATION=1 opt-in.",
)
async def test_real_vertex_generation_stream_is_opt_in() -> None:
    adapter = VertexGenerationAdapter(VertexGenerationConfig.from_environment())
    runtime = ProviderOrchestrator(generation=adapter)
    try:
        result = await runtime.generate(
            GenerationRequest(
                prompt="Reply with exactly: vertex stream verified",
                budget=RequestBudget(
                    timeout_seconds=30,
                    max_input_tokens=32,
                    max_output_tokens=32,
                ),
            )
        )
    finally:
        await adapter.aclose()

    assert result.text.strip()
    assert result.metadata.provider_id == "vertex-ai"
    assert result.metadata.token_usage.input_tokens > 0
    assert result.metadata.token_usage.output_tokens > 0
