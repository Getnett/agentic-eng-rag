"""Explicit opt-in smoke test for real Vertex streamed generation."""

from __future__ import annotations

import asyncio
import os

from rag_providers import (
    GenerationDelta,
    GenerationRequest,
    ProviderOrchestrator,
    RequestBudget,
    VertexGenerationAdapter,
    VertexGenerationConfig,
)

SMOKE_PROMPT = """You answer only from the supplied support context.
Context: A customer can reset their password from Settings > Security > Reset password.
Question: Where can a customer reset their password?
Answer in one short sentence."""


async def main() -> None:
    if os.getenv("RUN_VERTEX_INTEGRATION") != "1":
        raise SystemExit(
            "Set RUN_VERTEX_INTEGRATION=1 plus GOOGLE_CLOUD_PROJECT, "
            "GOOGLE_CLOUD_LOCATION, and VERTEX_GENERATION_MODEL to run the billed smoke test."
        )

    adapter = VertexGenerationAdapter(VertexGenerationConfig.from_environment())
    runtime = ProviderOrchestrator(generation=adapter)
    try:
        async for event in runtime.stream_generation(
            GenerationRequest(
                prompt=SMOKE_PROMPT,
                budget=RequestBudget(
                    timeout_seconds=30,
                    max_input_tokens=256,
                    max_output_tokens=96,
                ),
            )
        ):
            if isinstance(event, GenerationDelta):
                print(event.text, end="", flush=True)
        print()
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    asyncio.run(main())
