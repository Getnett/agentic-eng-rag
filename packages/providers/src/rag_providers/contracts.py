"""Stable contracts shared by model-provider adapters and orchestration."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class ProviderRole(StrEnum):
    """Model roles selectable by a model profile."""

    GENERATION = "generation"
    EMBEDDING = "embedding"
    REWRITE = "rewrite"
    RERANK = "rerank"


class ProviderErrorCode(StrEnum):
    """Provider-neutral failure categories exposed to orchestration."""

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_ROLE = "unsupported_role"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


RETRYABLE_PROVIDER_ERRORS = frozenset(
    {
        ProviderErrorCode.TIMEOUT,
        ProviderErrorCode.RATE_LIMITED,
        ProviderErrorCode.UNAVAILABLE,
    }
)


class ProviderAdapterError(RuntimeError):
    """Safe, normalized provider failure without SDK-specific details."""

    def __init__(
        self,
        *,
        code: ProviderErrorCode,
        message: str,
        provider_id: str,
        model_id: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_id = provider_id
        self.model_id = model_id
        self.retryable = code in RETRYABLE_PROVIDER_ERRORS


def _require_nonblank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank.")


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Non-secret identity and role support advertised by one adapter/model."""

    provider_id: str
    model_id: str
    roles: frozenset[ProviderRole]

    def __post_init__(self) -> None:
        _require_nonblank(self.provider_id, "provider_id")
        _require_nonblank(self.model_id, "model_id")
        if not self.roles:
            raise ValueError("roles must contain at least one provider role.")

    def supports(self, role: ProviderRole) -> bool:
        """Return whether this provider/model can perform the requested role."""
        return role in self.roles


@dataclass(frozen=True, slots=True)
class RequestBudget:
    """Hard request limits passed unchanged through the adapter boundary."""

    timeout_seconds: float
    max_input_tokens: int
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero.")
        if self.max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be greater than zero.")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be greater than zero when provided.")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized model token counts; values remain provider estimates."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("Token counts must not be negative.")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ProviderResultMetadata:
    """Comparable metadata attached to every normalized provider result."""

    provider_id: str
    model_id: str
    timeout_seconds: float
    token_usage: TokenUsage
    estimated_cost_usd: Decimal

    def __post_init__(self) -> None:
        _require_nonblank(self.provider_id, "provider_id")
        _require_nonblank(self.model_id, "model_id")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero.")
        if not self.estimated_cost_usd.is_finite() or self.estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd must be a finite non-negative estimate.")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    budget: RequestBudget

    def __post_init__(self) -> None:
        _require_nonblank(self.prompt, "prompt")
        if self.budget.max_output_tokens is None:
            raise ValueError("Generation requests require max_output_tokens.")


@dataclass(frozen=True, slots=True)
class GenerationDelta:
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("Generation deltas must not be empty.")


@dataclass(frozen=True, slots=True)
class GenerationComplete:
    metadata: ProviderResultMetadata


type GenerationEvent = GenerationDelta | GenerationComplete


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    metadata: ProviderResultMetadata

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("Generation results must not be empty.")


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    texts: tuple[str, ...]
    budget: RequestBudget

    def __post_init__(self) -> None:
        if not self.texts:
            raise ValueError("Embedding requests require at least one text.")
        if any(not text.strip() for text in self.texts):
            raise ValueError("Embedding request texts must not be blank.")
        if self.budget.max_output_tokens is not None:
            raise ValueError("Embedding requests do not accept max_output_tokens.")


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...]
    dimension: int
    metadata: ProviderResultMetadata

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("Embedding dimension must be greater than zero.")
        if not self.vectors:
            raise ValueError("Embedding results require at least one vector.")
        if any(len(vector) != self.dimension for vector in self.vectors):
            raise ValueError("Every embedding vector must match dimension.")
        if any(not math.isfinite(value) for vector in self.vectors for value in vector):
            raise ValueError("Embedding vectors must contain only finite values.")


@dataclass(frozen=True, slots=True)
class RewriteRequest:
    question: str
    max_variants: int
    budget: RequestBudget

    def __post_init__(self) -> None:
        _require_nonblank(self.question, "question")
        if not 1 <= self.max_variants <= 3:
            raise ValueError("max_variants must be between one and three.")
        if self.budget.max_output_tokens is None:
            raise ValueError("Rewrite requests require max_output_tokens.")


@dataclass(frozen=True, slots=True)
class RewriteResult:
    variants: tuple[str, ...]
    metadata: ProviderResultMetadata

    def __post_init__(self) -> None:
        if not self.variants or any(not variant.strip() for variant in self.variants):
            raise ValueError("Rewrite results require nonblank variants.")


@dataclass(frozen=True, slots=True)
class RerankRequest:
    query: str
    candidates: tuple[str, ...]
    top_n: int
    budget: RequestBudget

    def __post_init__(self) -> None:
        _require_nonblank(self.query, "query")
        if not self.candidates or any(not candidate.strip() for candidate in self.candidates):
            raise ValueError("Rerank requests require nonblank candidates.")
        if not 1 <= self.top_n <= len(self.candidates):
            raise ValueError("top_n must be between one and the candidate count.")
        if self.budget.max_output_tokens is not None:
            raise ValueError("Rerank requests do not accept max_output_tokens.")


@dataclass(frozen=True, slots=True)
class RerankResult:
    ranked_indices: tuple[int, ...]
    metadata: ProviderResultMetadata

    def __post_init__(self) -> None:
        if any(index < 0 for index in self.ranked_indices):
            raise ValueError("Rerank indices must not be negative.")
        if len(set(self.ranked_indices)) != len(self.ranked_indices):
            raise ValueError("Rerank indices must not contain duplicates.")


class GenerationAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]: ...


class EmbeddingAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...


class RewriteAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def rewrite(self, request: RewriteRequest) -> RewriteResult: ...


class RerankAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def rerank(self, request: RerankRequest) -> RerankResult: ...


def estimate_tokens(texts: Sequence[str]) -> int:
    """Return a deterministic whitespace-token estimate for tests and budgets."""
    return sum(len(text.split()) for text in texts)
