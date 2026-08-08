"""Manual POR-37 proof that orchestration is unchanged when adapter config swaps."""

from __future__ import annotations

import asyncio
import json

from rag_providers import (
    EmbeddingRequest,
    EmbeddingTask,
    FakeEmbeddingAdapter,
    FakeGenerationAdapter,
    GenerationRequest,
    ProviderOrchestrator,
    RequestBudget,
)


async def run_once(runtime: ProviderOrchestrator) -> dict[str, object]:
    """One orchestration function used unchanged for either fake configuration."""
    generation = await runtime.generate(
        GenerationRequest(
            prompt="How do I reset the device?",
            budget=RequestBudget(2, 20, 20),
        )
    )
    embedding = await runtime.embed(
        EmbeddingRequest(
            texts=("Reset the device from Settings.",),
            budget=RequestBudget(2, 20),
            task=EmbeddingTask.RETRIEVAL_DOCUMENT,
        )
    )
    return {
        "provider_id": generation.metadata.provider_id,
        "generation_model_id": generation.metadata.model_id,
        "embedding_model_id": embedding.metadata.model_id,
        "answer": generation.text,
        "embedding_dimension": embedding.dimension,
    }


def configured_runtime(label: str) -> ProviderOrchestrator:
    return ProviderOrchestrator(
        generation=FakeGenerationAdapter(
            provider_id=f"fake-{label}",
            model_id=f"generation-{label}",
            response_prefix=f"{label}: ",
        ),
        embedding=FakeEmbeddingAdapter(
            provider_id=f"fake-{label}",
            model_id=f"embedding-{label}",
            dimension=4,
        ),
    )


async def main() -> None:
    evidence = {
        "configuration_a": await run_once(configured_runtime("a")),
        "configuration_b": await run_once(configured_runtime("b")),
        "orchestration_function": "run_once",
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
