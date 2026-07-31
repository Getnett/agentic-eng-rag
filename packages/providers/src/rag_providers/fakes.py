"""Deterministic provider adapters used by tests and local examples."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

from rag_providers.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
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
    estimate_tokens,
)

DEFAULT_COST_PER_TOKEN_USD = Decimal("0.000001")


def _raise_configured_failure(
    capabilities: ProviderCapabilities,
    failure: ProviderErrorCode | None,
) -> None:
    if failure is None:
        return
    raise ProviderAdapterError(
        code=failure,
        message=f"Deterministic fake provider failure: {failure.value}.",
        provider_id=capabilities.provider_id,
        model_id=capabilities.model_id,
    )


def _validate_input_budget(
    *,
    token_count: int,
    capabilities: ProviderCapabilities,
    maximum: int,
) -> None:
    if token_count > maximum:
        raise ProviderAdapterError(
            code=ProviderErrorCode.INVALID_REQUEST,
            message="The request exceeds its input-token budget.",
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
        )


def _result_metadata(
    *,
    capabilities: ProviderCapabilities,
    timeout_seconds: float,
    input_tokens: int,
    output_tokens: int,
    cost_per_token_usd: Decimal,
) -> ProviderResultMetadata:
    usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    return ProviderResultMetadata(
        provider_id=capabilities.provider_id,
        model_id=capabilities.model_id,
        timeout_seconds=timeout_seconds,
        token_usage=usage,
        estimated_cost_usd=cost_per_token_usd * usage.total_tokens,
    )


@dataclass(frozen=True, slots=True)
class FakeGenerationAdapter:
    """Emit a deterministic streamed echo response and normalized metadata."""

    provider_id: str = "fake"
    model_id: str = "fake-generation-v1"
    response_prefix: str = "Grounded answer: "
    cost_per_token_usd: Decimal = DEFAULT_COST_PER_TOKEN_USD
    failure: ProviderErrorCode | None = None
    roles: frozenset[ProviderRole] = frozenset({ProviderRole.GENERATION})

    def __post_init__(self) -> None:
        if not self.cost_per_token_usd.is_finite() or self.cost_per_token_usd < 0:
            raise ValueError("cost_per_token_usd must be a finite non-negative estimate.")

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            model_id=self.model_id,
            roles=self.roles,
        )

    async def generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        capabilities = self.capabilities
        _raise_configured_failure(capabilities, self.failure)
        input_tokens = estimate_tokens((request.prompt,))
        _validate_input_budget(
            token_count=input_tokens,
            capabilities=capabilities,
            maximum=request.budget.max_input_tokens,
        )

        words = f"{self.response_prefix}{request.prompt.strip()}".split()
        output_limit = request.budget.max_output_tokens
        assert output_limit is not None
        selected_words = words[:output_limit]
        for index, word in enumerate(selected_words):
            suffix = "" if index == len(selected_words) - 1 else " "
            yield GenerationDelta(text=f"{word}{suffix}")
        yield GenerationComplete(
            metadata=_result_metadata(
                capabilities=capabilities,
                timeout_seconds=request.budget.timeout_seconds,
                input_tokens=input_tokens,
                output_tokens=len(selected_words),
                cost_per_token_usd=self.cost_per_token_usd,
            )
        )


@dataclass(frozen=True, slots=True)
class FakeEmbeddingAdapter:
    """Create stable SHA-256-derived vectors without provider SDKs or network I/O."""

    provider_id: str = "fake"
    model_id: str = "fake-embedding-v1"
    dimension: int = 8
    cost_per_token_usd: Decimal = DEFAULT_COST_PER_TOKEN_USD
    failure: ProviderErrorCode | None = None
    roles: frozenset[ProviderRole] = frozenset({ProviderRole.EMBEDDING})

    def __post_init__(self) -> None:
        if self.dimension <= 0 or self.dimension > hashlib.sha256().digest_size:
            raise ValueError("dimension must be between 1 and 32.")
        if not self.cost_per_token_usd.is_finite() or self.cost_per_token_usd < 0:
            raise ValueError("cost_per_token_usd must be a finite non-negative estimate.")

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            model_id=self.model_id,
            roles=self.roles,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        capabilities = self.capabilities
        _raise_configured_failure(capabilities, self.failure)
        input_tokens = estimate_tokens(request.texts)
        _validate_input_budget(
            token_count=input_tokens,
            capabilities=capabilities,
            maximum=request.budget.max_input_tokens,
        )
        vectors = tuple(self._vector(text) for text in request.texts)
        return EmbeddingResult(
            vectors=vectors,
            dimension=self.dimension,
            metadata=_result_metadata(
                capabilities=capabilities,
                timeout_seconds=request.budget.timeout_seconds,
                input_tokens=input_tokens,
                output_tokens=0,
                cost_per_token_usd=self.cost_per_token_usd,
            ),
        )

    def _vector(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode()).digest()
        return tuple(round((byte / 127.5) - 1.0, 8) for byte in digest[: self.dimension])
