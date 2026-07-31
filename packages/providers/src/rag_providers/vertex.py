"""Vertex AI generation adapter backed by the Google Gen AI SDK."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx
from google import genai
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.genai import errors, types

from rag_providers.contracts import (
    GenerationComplete,
    GenerationDelta,
    GenerationEvent,
    GenerationRequest,
    ProviderAdapterError,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderResultMetadata,
    ProviderRole,
    TokenUsage,
)

logger = logging.getLogger(__name__)

VERTEX_PROVIDER_ID = "vertex-ai"
PROJECT_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_PROJECT"
LOCATION_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_LOCATION"
MODEL_ENVIRONMENT_VARIABLE = "VERTEX_GENERATION_MODEL"
INPUT_COST_ENVIRONMENT_VARIABLE = "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD"
OUTPUT_COST_ENVIRONMENT_VARIABLE = "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD"
TOKENS_PER_MILLION = Decimal(1_000_000)


def _required_environment_value(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required and must not be blank.")
    return value.strip()


def _required_nonnegative_decimal(values: Mapping[str, str], name: str) -> Decimal:
    raw_value = _required_environment_value(values, name)
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal value.") from error
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative decimal value.")
    return value


@dataclass(frozen=True, slots=True)
class VertexGenerationConfig:
    """Non-secret Vertex routing and diagnostic-cost configuration."""

    project_id: str
    location: str
    model_id: str
    input_cost_per_million_tokens_usd: Decimal
    output_cost_per_million_tokens_usd: Decimal

    def __post_init__(self) -> None:
        for name, text_value in (
            ("project_id", self.project_id),
            ("location", self.location),
            ("model_id", self.model_id),
        ):
            if not text_value.strip() or any(character.isspace() for character in text_value):
                raise ValueError(f"{name} must be a nonblank value without whitespace.")
        for name, cost_value in (
            ("input_cost_per_million_tokens_usd", self.input_cost_per_million_tokens_usd),
            ("output_cost_per_million_tokens_usd", self.output_cost_per_million_tokens_usd),
        ):
            if not cost_value.is_finite() or cost_value < 0:
                raise ValueError(f"{name} must be a finite non-negative estimate.")

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str] | None = None,
    ) -> VertexGenerationConfig:
        """Read only non-secret routing values from the process environment."""
        environment = os.environ if values is None else values
        return cls(
            project_id=_required_environment_value(
                environment,
                PROJECT_ENVIRONMENT_VARIABLE,
            ),
            location=_required_environment_value(
                environment,
                LOCATION_ENVIRONMENT_VARIABLE,
            ),
            model_id=_required_environment_value(
                environment,
                MODEL_ENVIRONMENT_VARIABLE,
            ),
            input_cost_per_million_tokens_usd=_required_nonnegative_decimal(
                environment,
                INPUT_COST_ENVIRONMENT_VARIABLE,
            ),
            output_cost_per_million_tokens_usd=_required_nonnegative_decimal(
                environment,
                OUTPUT_COST_ENVIRONMENT_VARIABLE,
            ),
        )


class VertexStreamFactory(Protocol):
    """Small SDK seam used to keep adapter tests offline and deterministic."""

    async def __call__(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> AsyncIterator[types.GenerateContentResponse]: ...


class VertexTokenCounter(Protocol):
    """Small SDK seam for model-aware input budget enforcement."""

    async def __call__(
        self,
        *,
        model: str,
        contents: str,
    ) -> types.CountTokensResponse: ...


class VertexGenerationAdapter:
    """Stream Vertex text generation through the provider-neutral contract."""

    def __init__(
        self,
        config: VertexGenerationConfig,
        *,
        stream_factory: VertexStreamFactory | None = None,
        token_counter: VertexTokenCounter | None = None,
        close_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._stream_factory: VertexStreamFactory
        self._token_counter: VertexTokenCounter
        self._close_callback: Callable[[], Awaitable[None]] | None
        if stream_factory is None:
            try:
                client = genai.Client(
                    vertexai=True,
                    project=config.project_id,
                    location=config.location,
                    http_options=types.HttpOptions(api_version="v1"),
                )
            except Exception as error:
                mapped_error = self._map_sdk_error(error)
                logger.warning(
                    (
                        "Vertex client initialization failed: provider_id=%s "
                        "model_id=%s location=%s error_code=%s"
                    ),
                    VERTEX_PROVIDER_ID,
                    self._config.model_id,
                    self._config.location,
                    mapped_error.code.value,
                    extra=self._log_fields(error_code=mapped_error.code),
                )
                raise mapped_error from None
            self._stream_factory = client.aio.models.generate_content_stream
            self._token_counter = client.aio.models.count_tokens
            self._close_callback = client.aio.aclose
        else:
            if token_counter is None:
                raise ValueError("token_counter is required with an injected stream_factory.")
            self._stream_factory = stream_factory
            self._token_counter = token_counter
            self._close_callback = close_callback

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=VERTEX_PROVIDER_ID,
            model_id=self._config.model_id,
            roles=frozenset({ProviderRole.GENERATION}),
        )

    async def generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        output_limit = request.budget.max_output_tokens
        assert output_limit is not None
        request_config = types.GenerateContentConfig(
            max_output_tokens=output_limit,
            temperature=0,
            http_options=types.HttpOptions(
                api_version="v1",
                timeout=max(1, round(request.budget.timeout_seconds * 1000)),
            ),
        )
        usage_metadata: types.GenerateContentResponseUsageMetadata | None = None
        text_seen = False

        try:
            count_response = await self._token_counter(
                model=self._config.model_id,
                contents=request.prompt,
            )
            if count_response.total_tokens is None:
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "The model provider omitted the input-token count.",
                )
            if count_response.total_tokens > request.budget.max_input_tokens:
                raise self._error(
                    ProviderErrorCode.INVALID_REQUEST,
                    "The request exceeds its input-token budget.",
                )
            stream = await self._stream_factory(
                model=self._config.model_id,
                contents=request.prompt,
                config=request_config,
            )
            async for response in stream:
                if response.usage_metadata is not None:
                    usage_metadata = response.usage_metadata
                response_text = response.text
                if response_text:
                    text_seen = True
                    yield GenerationDelta(text=response_text)

            if not text_seen:
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "The model provider returned no answer text.",
                )
            metadata = self._result_metadata(request, usage_metadata)
        except ProviderAdapterError:
            raise
        except Exception as error:
            mapped_error = self._map_sdk_error(error)
            logger.warning(
                ("Vertex generation failed: provider_id=%s model_id=%s location=%s error_code=%s"),
                VERTEX_PROVIDER_ID,
                self._config.model_id,
                self._config.location,
                mapped_error.code.value,
                extra=self._log_fields(error_code=mapped_error.code),
            )
            raise mapped_error from None

        logger.info(
            (
                "Vertex generation completed: provider_id=%s model_id=%s location=%s "
                "input_tokens=%s output_tokens=%s estimated_cost_usd=%s"
            ),
            VERTEX_PROVIDER_ID,
            self._config.model_id,
            self._config.location,
            metadata.token_usage.input_tokens,
            metadata.token_usage.output_tokens,
            metadata.estimated_cost_usd,
            extra=self._log_fields(
                input_tokens=metadata.token_usage.input_tokens,
                output_tokens=metadata.token_usage.output_tokens,
                estimated_cost_usd=str(metadata.estimated_cost_usd),
            ),
        )
        yield GenerationComplete(metadata=metadata)

    async def aclose(self) -> None:
        """Release SDK HTTP resources when this adapter owns a client."""
        if self._close_callback is not None:
            await self._close_callback()

    def _result_metadata(
        self,
        request: GenerationRequest,
        usage: types.GenerateContentResponseUsageMetadata | None,
    ) -> ProviderResultMetadata:
        if (
            usage is None
            or usage.prompt_token_count is None
            or usage.candidates_token_count is None
        ):
            raise self._error(
                ProviderErrorCode.INVALID_RESPONSE,
                "The model provider omitted token-usage metadata.",
            )
        token_usage = TokenUsage(
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count + (usage.thoughts_token_count or 0),
        )
        estimated_cost = (
            self._config.input_cost_per_million_tokens_usd * token_usage.input_tokens
            + self._config.output_cost_per_million_tokens_usd * token_usage.output_tokens
        ) / TOKENS_PER_MILLION
        return ProviderResultMetadata(
            provider_id=VERTEX_PROVIDER_ID,
            model_id=self._config.model_id,
            timeout_seconds=request.budget.timeout_seconds,
            token_usage=token_usage,
            estimated_cost_usd=estimated_cost,
        )

    def _map_sdk_error(self, error: Exception) -> ProviderAdapterError:
        if isinstance(error, errors.APIError):
            if error.code in {408, 504}:
                code = ProviderErrorCode.TIMEOUT
            elif error.code == 429:
                code = ProviderErrorCode.RATE_LIMITED
            elif error.code >= 500:
                code = ProviderErrorCode.UNAVAILABLE
            elif error.code in {400, 401, 403, 404, 409, 422}:
                code = ProviderErrorCode.INVALID_REQUEST
            else:
                code = ProviderErrorCode.INVALID_RESPONSE
        elif isinstance(error, httpx.TimeoutException):
            code = ProviderErrorCode.TIMEOUT
        elif isinstance(error, (httpx.TransportError, RefreshError)):
            code = ProviderErrorCode.UNAVAILABLE
        elif isinstance(error, DefaultCredentialsError):
            code = ProviderErrorCode.INVALID_REQUEST
        elif isinstance(error, ValueError):
            code = ProviderErrorCode.INVALID_RESPONSE
        else:
            code = ProviderErrorCode.UNAVAILABLE
        return self._error(code, self._safe_error_message(code))

    def _error(self, code: ProviderErrorCode, message: str) -> ProviderAdapterError:
        return ProviderAdapterError(
            code=code,
            message=message,
            provider_id=VERTEX_PROVIDER_ID,
            model_id=self._config.model_id,
        )

    @staticmethod
    def _safe_error_message(code: ProviderErrorCode) -> str:
        messages = {
            ProviderErrorCode.INVALID_REQUEST: "The Vertex generation request is not permitted.",
            ProviderErrorCode.TIMEOUT: "Vertex generation exceeded the request timeout.",
            ProviderErrorCode.RATE_LIMITED: "Vertex generation is temporarily rate limited.",
            ProviderErrorCode.UNAVAILABLE: "Vertex generation is temporarily unavailable.",
            ProviderErrorCode.INVALID_RESPONSE: "Vertex returned an invalid generation response.",
        }
        return messages[code]

    def _log_fields(self, **fields: object) -> dict[str, object]:
        return {
            "provider_id": VERTEX_PROVIDER_ID,
            "model_id": self._config.model_id,
            "project_id": self._config.project_id,
            "location": self._config.location,
            **fields,
        }
