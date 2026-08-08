from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from google.genai import errors, types
from rag_providers import (
    EmbeddingAdapter,
    EmbeddingRequest,
    EmbeddingTask,
    FakeGenerationAdapter,
    ProviderAdapterError,
    ProviderErrorCode,
    ProviderOrchestrator,
    RequestBudget,
    TokenUsage,
    VertexEmbeddingAdapter,
    VertexEmbeddingConfig,
)

SENSITIVE_TEXT = "private source content must never be logged"


def embedding(values: list[float], *, tokens: float = 3) -> types.ContentEmbedding:
    return types.ContentEmbedding(
        values=values,
        statistics=types.ContentEmbeddingStatistics(token_count=tokens, truncated=False),
    )


class ScriptedEmbedContent:
    def __init__(
        self,
        responses: list[types.EmbedContentResponse | Exception],
    ) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[str], types.EmbedContentConfig]] = []

    async def __call__(
        self,
        *,
        model: str,
        contents: list[str],
        config: types.EmbedContentConfig,
    ) -> types.EmbedContentResponse:
        self.calls.append((model, contents, config))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def config(**overrides: object) -> VertexEmbeddingConfig:
    values: dict[str, object] = {
        "project_id": "customer-support-rag",
        "location": "europe-west1",
        "model_id": "text-embedding-test",
        "dimension": 3,
        "batch_size": 2,
        "max_attempts": 3,
        "initial_retry_delay_seconds": 0.1,
        "max_retry_delay_seconds": 0.2,
        "input_cost_per_million_characters_usd": Decimal("0.025"),
    }
    values.update(overrides)
    return VertexEmbeddingConfig(**values)  # type: ignore[arg-type]


def request(
    *texts: str,
    task: EmbeddingTask = EmbeddingTask.RETRIEVAL_DOCUMENT,
) -> EmbeddingRequest:
    return EmbeddingRequest(
        texts=tuple(texts or (SENSITIVE_TEXT,)),
        budget=RequestBudget(timeout_seconds=2.5, max_input_tokens=100),
        task=task,
    )


def api_error(status_code: int) -> errors.APIError:
    return errors.APIError(
        status_code,
        {"error": {"code": status_code, "message": SENSITIVE_TEXT}},
    )


def test_environment_configuration_is_complete_and_strict() -> None:
    values = {
        "GOOGLE_CLOUD_PROJECT": "customer-support-rag",
        "GOOGLE_CLOUD_LOCATION": "europe-west1",
        "VERTEX_EMBEDDING_MODEL": "text-embedding-test",
        "VERTEX_EMBEDDING_DIMENSION": "768",
        "VERTEX_EMBEDDING_BATCH_SIZE": "5",
        "VERTEX_EMBEDDING_MAX_ATTEMPTS": "3",
        "VERTEX_EMBEDDING_INITIAL_RETRY_DELAY_SECONDS": "0.25",
        "VERTEX_EMBEDDING_MAX_RETRY_DELAY_SECONDS": "2",
        "VERTEX_EMBEDDING_INPUT_COST_PER_MILLION_CHARACTERS_USD": "0.025",
    }

    parsed = VertexEmbeddingConfig.from_environment(values)

    assert parsed.model_id == "text-embedding-test"
    assert parsed.dimension == 768
    assert parsed.batch_size == 5
    assert parsed.max_attempts == 3
    assert parsed.input_cost_per_million_characters_usd == Decimal("0.025")
    for missing_name in values:
        incomplete = dict(values)
        del incomplete[missing_name]
        with pytest.raises(ValueError, match=missing_name):
            VertexEmbeddingConfig.from_environment(incomplete)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dimension", 0),
        ("batch_size", 6),
        ("max_attempts", 0),
        ("initial_retry_delay_seconds", -0.1),
        ("max_retry_delay_seconds", float("inf")),
        ("input_cost_per_million_characters_usd", Decimal("NaN")),
    ],
)
def test_configuration_rejects_invalid_limits(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        config(**{field: value})


def test_vertex_embedding_adapter_satisfies_contract_and_exposes_safe_profile() -> None:
    adapter = VertexEmbeddingAdapter(
        config(),
        embed_content=ScriptedEmbedContent([]),
    )
    contract: EmbeddingAdapter = adapter

    assert contract.capabilities.provider_id == "vertex-ai"
    assert contract.capabilities.model_id == "text-embedding-test"
    assert adapter.dimension == 3
    assert adapter.source_version_metadata() == {
        "provider_id": "vertex-ai",
        "model_id": "text-embedding-test",
        "dimension": 3,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task", "sdk_task"),
    [
        (EmbeddingTask.RETRIEVAL_DOCUMENT, "RETRIEVAL_DOCUMENT"),
        (EmbeddingTask.RETRIEVAL_QUERY, "RETRIEVAL_QUERY"),
    ],
)
async def test_document_and_query_use_identical_model_and_dimension(
    task: EmbeddingTask,
    sdk_task: str,
) -> None:
    factory = ScriptedEmbedContent(
        [types.EmbedContentResponse(embeddings=[embedding([0.1, 0.2, 0.3])])]
    )
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory)

    result = await ProviderOrchestrator(
        generation=FakeGenerationAdapter(), embedding=adapter
    ).embed(request("text", task=task))

    assert result.dimension == 3
    assert result.metadata.model_id == "text-embedding-test"
    model, contents, sdk_config = factory.calls[0]
    assert model == "text-embedding-test"
    assert contents == ["text"]
    assert sdk_config.task_type == sdk_task
    assert sdk_config.output_dimensionality == 3
    assert sdk_config.auto_truncate is False
    assert sdk_config.http_options is not None
    assert sdk_config.http_options.timeout == 2500
    assert sdk_config.http_options.retry_options is not None
    assert sdk_config.http_options.retry_options.attempts == 1


@pytest.mark.anyio
async def test_batches_in_order_and_normalizes_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = ScriptedEmbedContent(
        [
            types.EmbedContentResponse(
                embeddings=[embedding([0.1, 0.2, 0.3]), embedding([0.4, 0.5, 0.6])]
            ),
            types.EmbedContentResponse(embeddings=[embedding([0.7, 0.8, 0.9], tokens=2)]),
        ]
    )
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory)

    with caplog.at_level(logging.INFO, logger="rag_providers.vertex_embedding"):
        result = await ProviderOrchestrator(
            generation=FakeGenerationAdapter(), embedding=adapter
        ).embed(request(SENSITIVE_TEXT, "second", "third"))

    assert [call[1] for call in factory.calls] == [
        [SENSITIVE_TEXT, "second"],
        ["third"],
    ]
    assert result.vectors == (
        (0.1, 0.2, 0.3),
        (0.4, 0.5, 0.6),
        (0.7, 0.8, 0.9),
    )
    assert result.metadata.token_usage == TokenUsage(input_tokens=8, output_tokens=0)
    assert result.metadata.estimated_cost_usd == (
        Decimal("0.025") * sum(map(len, (SENSITIVE_TEXT, "second", "third")))
    ) / Decimal(1_000_000)
    assert SENSITIVE_TEXT not in caplog.text
    assert "vector_count=3" in caplog.text
    assert "dimension=3" in caplog.text


@pytest.mark.anyio
async def test_rejects_over_budget_input_before_any_billed_batch() -> None:
    factory = ScriptedEmbedContent(
        [types.EmbedContentResponse(embeddings=[embedding([0.1, 0.2, 0.3])])]
    )
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory)
    over_budget = EmbeddingRequest(
        texts=("無空格", "second batch input"),
        budget=RequestBudget(timeout_seconds=2.5, max_input_tokens=1),
        task=EmbeddingTask.RETRIEVAL_DOCUMENT,
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.embed(over_budget)

    assert raised.value.code is ProviderErrorCode.INVALID_REQUEST
    assert factory.calls == []


@pytest.mark.anyio
async def test_retries_only_retryable_batch_failures_with_bounded_backoff() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    factory = ScriptedEmbedContent(
        [
            api_error(429),
            api_error(503),
            types.EmbedContentResponse(embeddings=[embedding([0.1, 0.2, 0.3])]),
        ]
    )
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory, sleep=sleep)

    result = await adapter.embed(request("retry me"))

    assert result.dimension == 3
    assert len(factory.calls) == 3
    assert delays == [0.1, 0.2]


@pytest.mark.anyio
async def test_does_not_retry_nonretryable_failure_or_leak_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = ScriptedEmbedContent([api_error(400)])
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory)

    with caplog.at_level(logging.WARNING, logger="rag_providers.vertex_embedding"):
        with pytest.raises(ProviderAdapterError) as raised:
            await adapter.embed(request())

    assert raised.value.code is ProviderErrorCode.INVALID_REQUEST
    assert raised.value.retryable is False
    assert len(factory.calls) == 1
    assert SENSITIVE_TEXT not in caplog.text
    assert SENSITIVE_TEXT not in str(raised.value)


@pytest.mark.anyio
async def test_does_not_retry_unexpected_programming_failure() -> None:
    factory = ScriptedEmbedContent(
        [
            RuntimeError(SENSITIVE_TEXT),
            types.EmbedContentResponse(embeddings=[embedding([0.1, 0.2, 0.3])]),
        ]
    )
    adapter = VertexEmbeddingAdapter(config(), embed_content=factory)

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.embed(request("programming failure"))

    assert raised.value.code is ProviderErrorCode.INVALID_RESPONSE
    assert raised.value.retryable is False
    assert len(factory.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        types.EmbedContentResponse(embeddings=[]),
        types.EmbedContentResponse(embeddings=[embedding([0.1, 0.2])]),
        types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=[0.1, 0.2, 0.3])]),
        types.EmbedContentResponse(
            embeddings=[
                types.ContentEmbedding(
                    values=[0.1, 0.2, 0.3],
                    statistics=types.ContentEmbeddingStatistics(
                        token_count=3,
                        truncated=True,
                    ),
                )
            ]
        ),
    ],
)
async def test_rejects_invalid_provider_responses(
    response: types.EmbedContentResponse,
) -> None:
    adapter = VertexEmbeddingAdapter(
        config(),
        embed_content=ScriptedEmbedContent([response]),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.embed(request("invalid response"))

    assert raised.value.code is ProviderErrorCode.INVALID_RESPONSE


def test_empty_or_blank_text_is_rejected_before_adapter_call() -> None:
    budget = RequestBudget(timeout_seconds=1, max_input_tokens=10)
    with pytest.raises(ValueError, match="at least one text"):
        EmbeddingRequest(texts=(), budget=budget)
    with pytest.raises(ValueError, match="must not be blank"):
        EmbeddingRequest(texts=(" ",), budget=budget)


@pytest.mark.anyio
async def test_closes_owned_or_injected_client_resources() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    adapter = VertexEmbeddingAdapter(
        config(),
        embed_content=ScriptedEmbedContent([]),
        close_callback=close,
    )

    await adapter.aclose()

    assert closed is True
