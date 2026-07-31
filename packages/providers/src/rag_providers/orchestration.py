"""Minimal provider-neutral orchestration used by M1 callers and tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from rag_providers.contracts import (
    EmbeddingAdapter,
    EmbeddingRequest,
    EmbeddingResult,
    GenerationAdapter,
    GenerationComplete,
    GenerationDelta,
    GenerationEvent,
    GenerationRequest,
    GenerationResult,
    ProviderAdapterError,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderResultMetadata,
    ProviderRole,
)


class ProviderOrchestrator:
    """Call injected adapters while enforcing roles, budgets, and result contracts."""

    def __init__(
        self,
        *,
        generation: GenerationAdapter,
        embedding: EmbeddingAdapter,
    ) -> None:
        self._generation = generation
        self._embedding = embedding

    async def stream_generation(
        self,
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationEvent]:
        capabilities = self._require_role(self._generation.capabilities, ProviderRole.GENERATION)
        complete_seen = False
        delta_seen = False
        try:
            async with asyncio.timeout(request.budget.timeout_seconds):
                async for event in self._generation.generate(request):
                    if complete_seen:
                        raise self._protocol_error(
                            capabilities, "generation completed more than once"
                        )
                    if isinstance(event, GenerationComplete):
                        self._validate_metadata(
                            event.metadata, capabilities, request.budget.timeout_seconds
                        )
                        complete_seen = True
                    elif not isinstance(event, GenerationDelta):
                        raise self._protocol_error(
                            capabilities, "generation returned an unknown event"
                        )
                    else:
                        delta_seen = True
                    yield event
        except TimeoutError as error:
            raise self._timeout_error(capabilities) from error
        if not complete_seen:
            raise self._protocol_error(
                capabilities, "generation did not return completion metadata"
            )
        if not delta_seen:
            raise self._protocol_error(capabilities, "generation did not return answer text")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Collect a generation stream while retaining the streaming adapter contract."""
        chunks: list[str] = []
        metadata: ProviderResultMetadata | None = None
        async for event in self.stream_generation(request):
            if isinstance(event, GenerationDelta):
                chunks.append(event.text)
            else:
                metadata = event.metadata
        assert metadata is not None
        return GenerationResult(text="".join(chunks), metadata=metadata)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        capabilities = self._require_role(self._embedding.capabilities, ProviderRole.EMBEDDING)
        try:
            async with asyncio.timeout(request.budget.timeout_seconds):
                result = await self._embedding.embed(request)
        except TimeoutError as error:
            raise self._timeout_error(capabilities) from error
        self._validate_metadata(result.metadata, capabilities, request.budget.timeout_seconds)
        if len(result.vectors) != len(request.texts):
            raise self._protocol_error(
                capabilities, "embedding result count does not match request"
            )
        return result

    @staticmethod
    def _require_role(
        capabilities: ProviderCapabilities,
        role: ProviderRole,
    ) -> ProviderCapabilities:
        if not capabilities.supports(role):
            raise ProviderAdapterError(
                code=ProviderErrorCode.UNSUPPORTED_ROLE,
                message=(
                    f"Provider model {capabilities.provider_id}/{capabilities.model_id} "
                    f"does not support the {role.value} role."
                ),
                provider_id=capabilities.provider_id,
                model_id=capabilities.model_id,
            )
        return capabilities

    @staticmethod
    def _validate_metadata(
        metadata: ProviderResultMetadata,
        capabilities: ProviderCapabilities,
        timeout_seconds: float,
    ) -> None:
        if (
            metadata.provider_id != capabilities.provider_id
            or metadata.model_id != capabilities.model_id
            or metadata.timeout_seconds != timeout_seconds
        ):
            raise ProviderOrchestrator._protocol_error(
                capabilities,
                "result metadata does not match the configured adapter and request budget",
            )

    @staticmethod
    def _timeout_error(capabilities: ProviderCapabilities) -> ProviderAdapterError:
        return ProviderAdapterError(
            code=ProviderErrorCode.TIMEOUT,
            message="The model provider exceeded the request timeout.",
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
        )

    @staticmethod
    def _protocol_error(
        capabilities: ProviderCapabilities,
        reason: str,
    ) -> ProviderAdapterError:
        return ProviderAdapterError(
            code=ProviderErrorCode.INVALID_RESPONSE,
            message=f"The model provider returned an invalid response: {reason}.",
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
        )
