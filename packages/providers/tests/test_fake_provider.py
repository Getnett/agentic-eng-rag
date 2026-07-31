from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from rag_providers import (
    EmbeddingRequest,
    EmbeddingResult,
    FakeEmbeddingAdapter,
    FakeGenerationAdapter,
    GenerationComplete,
    GenerationEvent,
    GenerationRequest,
    ProviderAdapterError,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderOrchestrator,
    ProviderResultMetadata,
    ProviderRole,
    RequestBudget,
    TokenUsage,
)


def orchestrator(
    *,
    generation: FakeGenerationAdapter | None = None,
    embedding: FakeEmbeddingAdapter | None = None,
) -> ProviderOrchestrator:
    return ProviderOrchestrator(
        generation=generation or FakeGenerationAdapter(),
        embedding=embedding or FakeEmbeddingAdapter(),
    )


def generation_request(prompt: str = "Where is the guide?") -> GenerationRequest:
    return GenerationRequest(
        prompt=prompt,
        budget=RequestBudget(
            timeout_seconds=2.5,
            max_input_tokens=20,
            max_output_tokens=20,
        ),
    )


def embedding_request(*texts: str) -> EmbeddingRequest:
    return EmbeddingRequest(
        texts=tuple(texts or ("support article",)),
        budget=RequestBudget(timeout_seconds=1.5, max_input_tokens=20),
    )


@pytest.mark.anyio
async def test_generation_contract_is_deterministic_and_reports_estimates() -> None:
    runtime = orchestrator()

    first = await runtime.generate(generation_request())
    second = await runtime.generate(generation_request())

    assert first == second
    assert first.text == "Grounded answer: Where is the guide?"
    assert first.metadata.provider_id == "fake"
    assert first.metadata.model_id == "fake-generation-v1"
    assert first.metadata.timeout_seconds == 2.5
    assert first.metadata.token_usage == TokenUsage(input_tokens=4, output_tokens=6)
    assert first.metadata.token_usage.total_tokens == 10
    assert first.metadata.estimated_cost_usd == Decimal("0.000010")


@pytest.mark.anyio
async def test_embedding_contract_is_deterministic_and_batch_preserving() -> None:
    runtime = orchestrator(embedding=FakeEmbeddingAdapter(dimension=4))
    request = embedding_request("same text", "different text", "same text")

    first = await runtime.embed(request)
    second = await runtime.embed(request)

    assert first == second
    assert len(first.vectors) == 3
    assert first.vectors[0] == first.vectors[2]
    assert first.vectors[0] != first.vectors[1]
    assert first.dimension == 4
    assert first.metadata.provider_id == "fake"
    assert first.metadata.model_id == "fake-embedding-v1"
    assert first.metadata.timeout_seconds == 1.5
    assert first.metadata.token_usage == TokenUsage(input_tokens=6, output_tokens=0)
    assert first.metadata.estimated_cost_usd == Decimal("0.000006")


@pytest.mark.anyio
async def test_unsupported_role_fails_before_adapter_execution() -> None:
    runtime = orchestrator(
        generation=FakeGenerationAdapter(roles=frozenset({ProviderRole.EMBEDDING}))
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await runtime.generate(generation_request())

    assert raised.value.code is ProviderErrorCode.UNSUPPORTED_ROLE
    assert raised.value.retryable is False
    assert "generation role" in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "failure", "retryable"),
    [
        (operation, failure, retryable)
        for operation in ("generation", "embedding")
        for failure, retryable in (
            (ProviderErrorCode.INVALID_REQUEST, False),
            (ProviderErrorCode.TIMEOUT, True),
            (ProviderErrorCode.RATE_LIMITED, True),
            (ProviderErrorCode.UNAVAILABLE, True),
        )
    ],
)
async def test_fake_adapters_preserve_normalized_error_mapping(
    operation: str,
    failure: ProviderErrorCode,
    retryable: bool,
) -> None:
    runtime = orchestrator(
        generation=FakeGenerationAdapter(failure=failure) if operation == "generation" else None,
        embedding=FakeEmbeddingAdapter(failure=failure) if operation == "embedding" else None,
    )

    with pytest.raises(ProviderAdapterError) as raised:
        if operation == "generation":
            await runtime.generate(generation_request())
        else:
            await runtime.embed(embedding_request())

    assert raised.value.code is failure
    assert raised.value.retryable is retryable
    assert raised.value.provider_id == "fake"
    assert raised.value.model_id == f"fake-{operation}-v1"


@pytest.mark.anyio
async def test_budget_overflow_maps_to_non_retryable_invalid_request() -> None:
    request = GenerationRequest(
        prompt="one two three",
        budget=RequestBudget(timeout_seconds=1, max_input_tokens=2, max_output_tokens=2),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await orchestrator().generate(request)

    assert raised.value.code is ProviderErrorCode.INVALID_REQUEST
    assert raised.value.retryable is False


class SlowEmbeddingAdapter:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("slow", "slow-embedding", frozenset({ProviderRole.EMBEDDING}))

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        await asyncio.sleep(request.budget.timeout_seconds * 2)
        raise AssertionError("The timeout should cancel this adapter call.")


@pytest.mark.anyio
async def test_runtime_maps_deadline_expiry_to_retryable_timeout() -> None:
    runtime = ProviderOrchestrator(
        generation=FakeGenerationAdapter(),
        embedding=SlowEmbeddingAdapter(),
    )
    request = EmbeddingRequest(
        texts=("bounded",),
        budget=RequestBudget(timeout_seconds=0.01, max_input_tokens=2),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await runtime.embed(request)

    assert raised.value.code is ProviderErrorCode.TIMEOUT
    assert raised.value.retryable is True


@pytest.mark.anyio
async def test_consumer_backpressure_does_not_consume_provider_timeout() -> None:
    runtime = orchestrator()
    request = GenerationRequest(
        prompt="healthy stream",
        budget=RequestBudget(
            timeout_seconds=0.01,
            max_input_tokens=4,
            max_output_tokens=8,
        ),
    )
    events: list[GenerationEvent] = []

    async for event in runtime.stream_generation(request):
        events.append(event)
        await asyncio.sleep(0.02)

    assert isinstance(events[-1], GenerationComplete)


class MissingCompletionAdapter:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("broken", "broken-gen", frozenset({ProviderRole.GENERATION}))

    async def generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        if request.prompt:
            return
        yield GenerationComplete(
            ProviderResultMetadata(
                provider_id="broken",
                model_id="broken-gen",
                timeout_seconds=request.budget.timeout_seconds,
                token_usage=TokenUsage(0, 0),
                estimated_cost_usd=Decimal("0"),
            )
        )


@pytest.mark.anyio
async def test_runtime_rejects_missing_completion_metadata() -> None:
    runtime = ProviderOrchestrator(
        generation=MissingCompletionAdapter(),
        embedding=FakeEmbeddingAdapter(),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await runtime.generate(generation_request())

    assert raised.value.code is ProviderErrorCode.INVALID_RESPONSE
    assert raised.value.retryable is False
