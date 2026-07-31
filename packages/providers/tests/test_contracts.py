from __future__ import annotations

import pytest
from rag_providers import (
    EmbeddingAdapter,
    FakeEmbeddingAdapter,
    FakeGenerationAdapter,
    GenerationAdapter,
    ProviderCapabilities,
    ProviderRole,
    RequestBudget,
)


def test_fake_adapters_satisfy_protocols_at_type_check_time() -> None:
    generation = FakeGenerationAdapter()
    embedding = FakeEmbeddingAdapter()

    generation_contract: GenerationAdapter = generation
    embedding_contract: EmbeddingAdapter = embedding
    assert generation_contract.capabilities.supports(ProviderRole.GENERATION)
    assert embedding_contract.capabilities.supports(ProviderRole.EMBEDDING)


def test_capabilities_require_safe_identity_and_at_least_one_role() -> None:
    with pytest.raises(ValueError, match="provider_id"):
        ProviderCapabilities(" ", "model", frozenset({ProviderRole.GENERATION}))
    with pytest.raises(ValueError, match="model_id"):
        ProviderCapabilities("provider", " ", frozenset({ProviderRole.GENERATION}))
    with pytest.raises(ValueError, match="at least one"):
        ProviderCapabilities("provider", "model", frozenset())


@pytest.mark.parametrize(
    "budget",
    [
        RequestBudget(timeout_seconds=1, max_input_tokens=1),
        RequestBudget(timeout_seconds=1, max_input_tokens=1, max_output_tokens=1),
    ],
)
def test_request_budgets_support_embedding_and_generation(budget: RequestBudget) -> None:
    assert budget.timeout_seconds == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0, "max_input_tokens": 1},
        {"timeout_seconds": float("inf"), "max_input_tokens": 1},
        {"timeout_seconds": 1, "max_input_tokens": 0},
        {"timeout_seconds": 1, "max_input_tokens": 1, "max_output_tokens": 0},
    ],
)
def test_invalid_request_budgets_fail_early(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RequestBudget(**kwargs)  # type: ignore[arg-type]
