"""Vertex AI text-embedding adapter backed by the Google Gen AI SDK."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypedDict

import httpx
from google import genai
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.genai import errors, types

from rag_providers.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingTask,
    ProviderAdapterError,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderResultMetadata,
    ProviderRole,
    TokenUsage,
)
from rag_providers.vertex import (
    LOCATION_ENVIRONMENT_VARIABLE,
    PROJECT_ENVIRONMENT_VARIABLE,
    VERTEX_PROVIDER_ID,
)

logger = logging.getLogger(__name__)

MODEL_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_MODEL"
DIMENSION_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_DIMENSION"
BATCH_SIZE_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_BATCH_SIZE"
MAX_ATTEMPTS_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_MAX_ATTEMPTS"
INITIAL_RETRY_DELAY_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_INITIAL_RETRY_DELAY_SECONDS"
MAX_RETRY_DELAY_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_MAX_RETRY_DELAY_SECONDS"
INPUT_COST_ENVIRONMENT_VARIABLE = "VERTEX_EMBEDDING_INPUT_COST_PER_MILLION_CHARACTERS_USD"
CHARACTERS_PER_MILLION = Decimal(1_000_000)
MAX_ONLINE_BATCH_SIZE = 5


def _required_environment_value(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required and must not be blank.")
    return value.strip()


def _required_positive_integer(values: Mapping[str, str], name: str) -> int:
    raw_value = _required_environment_value(values, name)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer value.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _required_nonnegative_decimal(values: Mapping[str, str], name: str) -> Decimal:
    raw_value = _required_environment_value(values, name)
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal value.") from error
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative decimal value.")
    return value


def _required_nonnegative_float(values: Mapping[str, str], name: str) -> float:
    raw_value = _required_environment_value(values, name)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a numeric value.") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative value.")
    return value


@dataclass(frozen=True, slots=True)
class VertexEmbeddingConfig:
    """Immutable Vertex routing, batching, retry, and cost configuration."""

    project_id: str
    location: str
    model_id: str
    dimension: int
    batch_size: int
    max_attempts: int
    initial_retry_delay_seconds: float
    max_retry_delay_seconds: float
    input_cost_per_million_characters_usd: Decimal

    def __post_init__(self) -> None:
        for name, text_value in (
            ("project_id", self.project_id),
            ("location", self.location),
            ("model_id", self.model_id),
        ):
            if not text_value.strip() or any(character.isspace() for character in text_value):
                raise ValueError(f"{name} must be a nonblank value without whitespace.")
        for name, integer_value in (
            ("dimension", self.dimension),
            ("max_attempts", self.max_attempts),
        ):
            if integer_value <= 0:
                raise ValueError(f"{name} must be greater than zero.")
        if not 1 <= self.batch_size <= MAX_ONLINE_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {MAX_ONLINE_BATCH_SIZE}.")
        for name, delay in (
            ("initial_retry_delay_seconds", self.initial_retry_delay_seconds),
            ("max_retry_delay_seconds", self.max_retry_delay_seconds),
        ):
            if not math.isfinite(delay) or delay < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if self.max_retry_delay_seconds < self.initial_retry_delay_seconds:
            raise ValueError(
                "max_retry_delay_seconds must be at least initial_retry_delay_seconds."
            )
        if (
            not self.input_cost_per_million_characters_usd.is_finite()
            or self.input_cost_per_million_characters_usd < 0
        ):
            raise ValueError(
                "input_cost_per_million_characters_usd must be a finite non-negative estimate."
            )

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str] | None = None,
    ) -> VertexEmbeddingConfig:
        environment = os.environ if values is None else values
        return cls(
            project_id=_required_environment_value(environment, PROJECT_ENVIRONMENT_VARIABLE),
            location=_required_environment_value(environment, LOCATION_ENVIRONMENT_VARIABLE),
            model_id=_required_environment_value(environment, MODEL_ENVIRONMENT_VARIABLE),
            dimension=_required_positive_integer(environment, DIMENSION_ENVIRONMENT_VARIABLE),
            batch_size=_required_positive_integer(environment, BATCH_SIZE_ENVIRONMENT_VARIABLE),
            max_attempts=_required_positive_integer(environment, MAX_ATTEMPTS_ENVIRONMENT_VARIABLE),
            initial_retry_delay_seconds=_required_nonnegative_float(
                environment, INITIAL_RETRY_DELAY_ENVIRONMENT_VARIABLE
            ),
            max_retry_delay_seconds=_required_nonnegative_float(
                environment, MAX_RETRY_DELAY_ENVIRONMENT_VARIABLE
            ),
            input_cost_per_million_characters_usd=_required_nonnegative_decimal(
                environment, INPUT_COST_ENVIRONMENT_VARIABLE
            ),
        )


class VertexEmbedContent(Protocol):
    """Small SDK seam that keeps adapter tests offline."""

    async def __call__(
        self,
        *,
        model: str,
        contents: list[str],
        config: types.EmbedContentConfig,
    ) -> types.EmbedContentResponse: ...


class EmbeddingProfileMetadata(TypedDict):
    """Serializable identity attached to every embedded source version."""

    provider_id: str
    model_id: str
    dimension: int


class VertexEmbeddingAdapter:
    """Batch and normalize Vertex text embeddings for documents and queries."""

    def __init__(
        self,
        config: VertexEmbeddingConfig,
        *,
        embed_content: VertexEmbedContent | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        close_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._embed_content: VertexEmbedContent
        self._close_callback: Callable[[], Awaitable[None]] | None
        if embed_content is None:
            try:
                client = genai.Client(
                    vertexai=True,
                    project=config.project_id,
                    location=config.location,
                    http_options=types.HttpOptions(api_version="v1"),
                )
            except Exception as error:
                raise self._map_sdk_error(error) from None
            self._embed_content = client.aio.models.embed_content
            self._close_callback = client.aio.aclose
        else:
            self._embed_content = embed_content
            self._close_callback = close_callback

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=VERTEX_PROVIDER_ID,
            model_id=self._config.model_id,
            roles=frozenset({ProviderRole.EMBEDDING}),
        )

    @property
    def dimension(self) -> int:
        """Expose the immutable dimension needed by persistence configuration."""
        return self._config.dimension

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        vectors: list[tuple[float, ...]] = []
        input_tokens = 0
        sdk_task = self._sdk_task(request.task)

        for batch_number, batch in enumerate(self._batches(request.texts), start=1):
            response = await self._embed_batch(
                request=request,
                batch=batch,
                task_type=sdk_task,
                batch_number=batch_number,
            )
            batch_vectors, batch_tokens = self._normalize_response(response, len(batch))
            vectors.extend(batch_vectors)
            input_tokens += batch_tokens

        if input_tokens > request.budget.max_input_tokens:
            raise self._error(
                ProviderErrorCode.INVALID_REQUEST,
                "The embedding request exceeds its input-token budget.",
            )

        character_count = sum(len(text) for text in request.texts)
        metadata = ProviderResultMetadata(
            provider_id=VERTEX_PROVIDER_ID,
            model_id=self._config.model_id,
            timeout_seconds=request.budget.timeout_seconds,
            token_usage=TokenUsage(input_tokens=input_tokens, output_tokens=0),
            estimated_cost_usd=(
                self._config.input_cost_per_million_characters_usd * character_count
            )
            / CHARACTERS_PER_MILLION,
        )
        logger.info(
            (
                "Vertex embedding completed: provider_id=%s model_id=%s location=%s "
                "task=%s vector_count=%s dimension=%s input_tokens=%s "
                "estimated_cost_usd=%s"
            ),
            VERTEX_PROVIDER_ID,
            self._config.model_id,
            self._config.location,
            request.task.value,
            len(vectors),
            self._config.dimension,
            input_tokens,
            metadata.estimated_cost_usd,
            extra=self._log_fields(
                task=request.task.value,
                vector_count=len(vectors),
                dimension=self._config.dimension,
                input_tokens=input_tokens,
                estimated_cost_usd=str(metadata.estimated_cost_usd),
            ),
        )
        return EmbeddingResult(
            vectors=tuple(vectors),
            dimension=self._config.dimension,
            metadata=metadata,
        )

    async def aclose(self) -> None:
        if self._close_callback is not None:
            await self._close_callback()

    def source_version_metadata(self) -> EmbeddingProfileMetadata:
        """Return the stable, non-secret model identity stored with a source version."""
        return {
            "provider_id": VERTEX_PROVIDER_ID,
            "model_id": self._config.model_id,
            "dimension": self._config.dimension,
        }

    def _batches(self, texts: Sequence[str]) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(texts[index : index + self._config.batch_size])
            for index in range(0, len(texts), self._config.batch_size)
        )

    async def _embed_batch(
        self,
        *,
        request: EmbeddingRequest,
        batch: tuple[str, ...],
        task_type: str,
        batch_number: int,
    ) -> types.EmbedContentResponse:
        request_config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._config.dimension,
            auto_truncate=False,
            http_options=types.HttpOptions(
                api_version="v1",
                timeout=max(1, round(request.budget.timeout_seconds * 1000)),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        delay = self._config.initial_retry_delay_seconds
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                return await self._embed_content(
                    model=self._config.model_id,
                    contents=list(batch),
                    config=request_config,
                )
            except Exception as error:
                mapped_error = self._map_sdk_error(error)
                if not mapped_error.retryable or attempt == self._config.max_attempts:
                    logger.warning(
                        (
                            "Vertex embedding failed: provider_id=%s model_id=%s "
                            "location=%s batch_number=%s attempt=%s error_code=%s"
                        ),
                        VERTEX_PROVIDER_ID,
                        self._config.model_id,
                        self._config.location,
                        batch_number,
                        attempt,
                        mapped_error.code.value,
                        extra=self._log_fields(
                            batch_number=batch_number,
                            attempt=attempt,
                            error_code=mapped_error.code.value,
                        ),
                    )
                    raise mapped_error from None
                await self._sleep(delay)
                delay = min(delay * 2, self._config.max_retry_delay_seconds)
        raise AssertionError("Embedding retry loop exhausted without returning or raising.")

    def _normalize_response(
        self,
        response: types.EmbedContentResponse,
        expected_count: int,
    ) -> tuple[list[tuple[float, ...]], int]:
        embeddings = response.embeddings
        if embeddings is None or len(embeddings) != expected_count:
            raise self._error(
                ProviderErrorCode.INVALID_RESPONSE,
                "Vertex returned an unexpected embedding count.",
            )
        vectors: list[tuple[float, ...]] = []
        token_count = 0
        for embedding in embeddings:
            values = embedding.values
            statistics = embedding.statistics
            if values is None or len(values) != self._config.dimension:
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "Vertex returned an embedding with an unexpected dimension.",
                )
            if any(not math.isfinite(value) for value in values):
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "Vertex returned a non-finite embedding value.",
                )
            if (
                statistics is None
                or statistics.token_count is None
                or not statistics.token_count.is_integer()
                or statistics.token_count < 0
            ):
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "Vertex omitted valid embedding token metadata.",
                )
            if statistics.truncated:
                raise self._error(
                    ProviderErrorCode.INVALID_RESPONSE,
                    "Vertex unexpectedly truncated embedding input.",
                )
            vectors.append(tuple(values))
            token_count += int(statistics.token_count)
        return vectors, token_count

    @staticmethod
    def _sdk_task(task: EmbeddingTask) -> str:
        return {
            EmbeddingTask.RETRIEVAL_DOCUMENT: "RETRIEVAL_DOCUMENT",
            EmbeddingTask.RETRIEVAL_QUERY: "RETRIEVAL_QUERY",
        }[task]

    def _map_sdk_error(self, error: Exception) -> ProviderAdapterError:
        if isinstance(error, ProviderAdapterError):
            return error
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
        return {
            ProviderErrorCode.INVALID_REQUEST: "The Vertex embedding request is not permitted.",
            ProviderErrorCode.TIMEOUT: "Vertex embedding exceeded the request timeout.",
            ProviderErrorCode.RATE_LIMITED: "Vertex embedding is temporarily rate limited.",
            ProviderErrorCode.UNAVAILABLE: "Vertex embedding is temporarily unavailable.",
            ProviderErrorCode.INVALID_RESPONSE: "Vertex returned an invalid embedding response.",
        }[code]

    def _log_fields(self, **fields: object) -> dict[str, object]:
        return {
            "provider_id": VERTEX_PROVIDER_ID,
            "model_id": self._config.model_id,
            "project_id": self._config.project_id,
            "location": self._config.location,
            **fields,
        }
