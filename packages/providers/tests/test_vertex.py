from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
from google.auth.exceptions import DefaultCredentialsError
from google.genai import errors, types
from rag_providers import (
    GenerationAdapter,
    GenerationComplete,
    GenerationDelta,
    GenerationRequest,
    ProviderAdapterError,
    ProviderErrorCode,
    ProviderOrchestrator,
    RequestBudget,
    TokenUsage,
    VertexGenerationAdapter,
    VertexGenerationConfig,
)

SENSITIVE_PROMPT = "private support prompt must never be logged"


class ScriptedStreamFactory:
    def __init__(
        self,
        responses: tuple[types.GenerateContentResponse, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.responses = responses
        self.failure = failure
        self.calls: list[tuple[str, str, types.GenerateContentConfig]] = []

    async def __call__(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> AsyncIterator[types.GenerateContentResponse]:
        self.calls.append((model, contents, config))
        if self.failure is not None:
            raise self.failure

        async def responses() -> AsyncIterator[types.GenerateContentResponse]:
            for response in self.responses:
                yield response

        return responses()


def vertex_config() -> VertexGenerationConfig:
    return VertexGenerationConfig(
        project_id="customer-support-rag",
        location="europe-west1",
        model_id="gemini-test",
        input_cost_per_million_tokens_usd=Decimal("0.10"),
        output_cost_per_million_tokens_usd=Decimal("0.40"),
    )


def generation_request(prompt: str = SENSITIVE_PROMPT) -> GenerationRequest:
    return GenerationRequest(
        prompt=prompt,
        budget=RequestBudget(
            timeout_seconds=2.5,
            max_input_tokens=20,
            max_output_tokens=12,
        ),
    )


def successful_responses() -> tuple[types.GenerateContentResponse, ...]:
    return (
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="Grounded ")],
                    )
                )
            ]
        ),
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="answer.")],
                    )
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=10,
                candidates_token_count=4,
                thoughts_token_count=3,
                total_token_count=17,
            ),
        ),
    )


def api_error(status_code: int) -> errors.APIError:
    return errors.APIError(
        status_code,
        {"error": {"code": status_code, "message": SENSITIVE_PROMPT}},
    )


def test_environment_configuration_requires_project_location_and_model() -> None:
    config = VertexGenerationConfig.from_environment(
        {
            "GOOGLE_CLOUD_PROJECT": "customer-support-rag",
            "GOOGLE_CLOUD_LOCATION": "europe-west1",
            "VERTEX_GENERATION_MODEL": "gemini-test",
            "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD": "0.10",
            "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD": "0.40",
        }
    )

    assert config == VertexGenerationConfig(
        project_id="customer-support-rag",
        location="europe-west1",
        model_id="gemini-test",
        input_cost_per_million_tokens_usd=Decimal("0.10"),
        output_cost_per_million_tokens_usd=Decimal("0.40"),
    )

    for missing_name in (
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "VERTEX_GENERATION_MODEL",
        "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD",
        "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD",
    ):
        values = {
            "GOOGLE_CLOUD_PROJECT": "customer-support-rag",
            "GOOGLE_CLOUD_LOCATION": "europe-west1",
            "VERTEX_GENERATION_MODEL": "gemini-test",
            "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD": "0.10",
            "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD": "0.40",
        }
        del values[missing_name]
        with pytest.raises(ValueError, match=missing_name):
            VertexGenerationConfig.from_environment(values)


@pytest.mark.parametrize("invalid_cost", ["", "unknown", "-0.01", "NaN", "Infinity"])
def test_environment_configuration_rejects_invalid_pricing(invalid_cost: str) -> None:
    values = {
        "GOOGLE_CLOUD_PROJECT": "customer-support-rag",
        "GOOGLE_CLOUD_LOCATION": "europe-west1",
        "VERTEX_GENERATION_MODEL": "gemini-test",
        "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD": invalid_cost,
        "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD": "0.40",
    }

    with pytest.raises(ValueError, match="INPUT_COST"):
        VertexGenerationConfig.from_environment(values)


def test_vertex_adapter_satisfies_generation_contract() -> None:
    adapter = VertexGenerationAdapter(
        vertex_config(),
        stream_factory=ScriptedStreamFactory(successful_responses()),
    )
    generation_adapter: GenerationAdapter = adapter

    assert generation_adapter.capabilities.provider_id == "vertex-ai"
    assert generation_adapter.capabilities.model_id == "gemini-test"


@pytest.mark.anyio
async def test_streams_normalized_events_and_safe_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = ScriptedStreamFactory(successful_responses())
    adapter = VertexGenerationAdapter(vertex_config(), stream_factory=factory)
    runtime = ProviderOrchestrator(generation=adapter)

    with caplog.at_level(logging.INFO, logger="rag_providers.vertex"):
        result = await runtime.generate(generation_request())

    assert result.text == "Grounded answer."
    assert result.metadata.provider_id == "vertex-ai"
    assert result.metadata.model_id == "gemini-test"
    assert result.metadata.timeout_seconds == 2.5
    assert result.metadata.token_usage == TokenUsage(input_tokens=10, output_tokens=7)
    assert result.metadata.estimated_cost_usd == Decimal("0.0000038")
    assert len(factory.calls) == 1
    model, contents, sdk_config = factory.calls[0]
    assert model == "gemini-test"
    assert contents == SENSITIVE_PROMPT
    assert sdk_config.max_output_tokens == 12
    assert sdk_config.temperature == 0
    assert sdk_config.http_options is not None
    assert sdk_config.http_options.api_version == "v1"
    assert sdk_config.http_options.timeout == 2500
    assert SENSITIVE_PROMPT not in caplog.text
    assert "customer-support-rag" not in caplog.text
    assert "Vertex generation completed:" in caplog.text
    assert "provider_id=vertex-ai" in caplog.text
    assert "model_id=gemini-test" in caplog.text
    assert "location=europe-west1" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (api_error(400), ProviderErrorCode.INVALID_REQUEST, False),
        (api_error(401), ProviderErrorCode.INVALID_REQUEST, False),
        (api_error(403), ProviderErrorCode.INVALID_REQUEST, False),
        (api_error(404), ProviderErrorCode.INVALID_REQUEST, False),
        (api_error(408), ProviderErrorCode.TIMEOUT, True),
        (api_error(429), ProviderErrorCode.RATE_LIMITED, True),
        (api_error(500), ProviderErrorCode.UNAVAILABLE, True),
        (httpx.ReadTimeout(SENSITIVE_PROMPT), ProviderErrorCode.TIMEOUT, True),
        (httpx.ConnectError(SENSITIVE_PROMPT), ProviderErrorCode.UNAVAILABLE, True),
        (
            DefaultCredentialsError(SENSITIVE_PROMPT),  # type: ignore[no-untyped-call]
            ProviderErrorCode.INVALID_REQUEST,
            False,
        ),
        (RuntimeError(SENSITIVE_PROMPT), ProviderErrorCode.UNAVAILABLE, True),
    ],
)
async def test_maps_sdk_failures_without_leaking_provider_details(
    failure: Exception,
    expected_code: ProviderErrorCode,
    retryable: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = VertexGenerationAdapter(
        vertex_config(),
        stream_factory=ScriptedStreamFactory(failure=failure),
    )
    runtime = ProviderOrchestrator(generation=adapter)

    with caplog.at_level(logging.WARNING, logger="rag_providers.vertex"):
        with pytest.raises(ProviderAdapterError) as raised:
            await runtime.generate(generation_request())

    assert raised.value.code is expected_code
    assert raised.value.retryable is retryable
    assert raised.value.provider_id == "vertex-ai"
    assert raised.value.model_id == "gemini-test"
    assert SENSITIVE_PROMPT not in str(raised.value)
    assert SENSITIVE_PROMPT not in caplog.text
    assert raised.value.__suppress_context__ is True


def test_maps_client_initialization_credentials_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_client_creation(**_kwargs: object) -> None:
        raise DefaultCredentialsError(SENSITIVE_PROMPT)  # type: ignore[no-untyped-call]

    monkeypatch.setattr("rag_providers.vertex.genai.Client", fail_client_creation)

    with caplog.at_level(logging.WARNING, logger="rag_providers.vertex"):
        with pytest.raises(ProviderAdapterError) as raised:
            VertexGenerationAdapter(vertex_config())

    assert raised.value.code is ProviderErrorCode.INVALID_REQUEST
    assert raised.value.retryable is False
    assert raised.value.__suppress_context__ is True
    assert SENSITIVE_PROMPT not in str(raised.value)
    assert SENSITIVE_PROMPT not in caplog.text


@pytest.mark.anyio
async def test_rejects_over_budget_prompt_before_vertex_call() -> None:
    factory = ScriptedStreamFactory(successful_responses())
    adapter = VertexGenerationAdapter(vertex_config(), stream_factory=factory)
    runtime = ProviderOrchestrator(generation=adapter)
    request = GenerationRequest(
        prompt="one two three",
        budget=RequestBudget(
            timeout_seconds=1,
            max_input_tokens=2,
            max_output_tokens=2,
        ),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await runtime.generate(request)

    assert raised.value.code is ProviderErrorCode.INVALID_REQUEST
    assert factory.calls == []


@pytest.mark.anyio
async def test_missing_text_or_usage_is_a_safe_terminal_error() -> None:
    scenarios = (
        (
            types.GenerateContentResponse(
                usage_metadata=types.GenerateContentResponseUsageMetadata()
            ),
        ),
        (
            types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[types.Part(text="answer")],
                        )
                    )
                ]
            ),
        ),
    )

    for responses in scenarios:
        adapter = VertexGenerationAdapter(
            vertex_config(),
            stream_factory=ScriptedStreamFactory(responses),
        )
        runtime = ProviderOrchestrator(generation=adapter)
        with pytest.raises(ProviderAdapterError) as raised:
            await runtime.generate(generation_request())
        assert raised.value.code is ProviderErrorCode.INVALID_RESPONSE


@pytest.mark.anyio
async def test_close_callback_releases_owned_client_resources() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    adapter = VertexGenerationAdapter(
        vertex_config(),
        stream_factory=ScriptedStreamFactory(successful_responses()),
        close_callback=close,
    )

    await adapter.aclose()

    assert closed is True


@pytest.mark.anyio
async def test_raw_adapter_event_order_matches_generation_contract() -> None:
    adapter = VertexGenerationAdapter(
        vertex_config(),
        stream_factory=ScriptedStreamFactory(successful_responses()),
    )

    events = [event async for event in adapter.generate(generation_request())]

    assert [type(event) for event in events] == [
        GenerationDelta,
        GenerationDelta,
        GenerationComplete,
    ]
