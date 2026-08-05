"""`CompositeModelProvider`: dispatches to the correct underlying provider-specific
`ModelProvider` adapter based on the resolved model's `provider` field (ADR-029).

This is the one place that knows more than one provider exists. Every other adapter
(`BedrockModelProvider`, `OpenAIModelProvider`) implements `domain.ports.ModelProvider`
without any awareness of the other, and the domain/application layers only ever see
`domain.ports.ModelProvider` — never this class specifically, or any concrete provider
adapter (ADR-002).
"""

from collections.abc import Iterator, Mapping

from adapters.common.model_resolution import resolve_model
from domain.enums import ProviderErrorCategory, ProviderName
from domain.errors import ProviderError
from domain.ports import ModelCatalogue, ModelProvider, StreamingModelProvider
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk


class CompositeModelProvider:
    def __init__(
        self,
        model_catalogue: ModelCatalogue,
        providers: Mapping[ProviderName, ModelProvider],
    ) -> None:
        self._model_catalogue = model_catalogue
        self._providers = dict(providers)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return self._resolve_provider(request).invoke(request)

    def invoke_stream(self, request: ProviderRequest) -> Iterator[ProviderResponseChunk]:
        """`domain.ports.StreamingModelProvider.invoke_stream` (ADR-032, Phase 10c):
        dispatches exactly like `invoke`, plus an `isinstance` check against
        `StreamingModelProvider` -- the resolved model's provider adapter may not
        implement streaming at all (it's an optional capability, not part of
        `ModelProvider` itself), which is a routing-time fact about that specific
        adapter, not something `InvocationOrchestrator` should need to know how to
        detect on its own.
        """
        model = resolve_model(request.model_alias, self._model_catalogue)
        provider = self._resolve_provider(request)
        if not isinstance(provider, StreamingModelProvider):
            raise ProviderError(
                f"The provider adapter for provider {model.provider.value!r} does not "
                f"support streaming (model_alias {model.model_alias!r}).",
                category=ProviderErrorCategory.PERMANENT,
            )
        return provider.invoke_stream(request)

    def _resolve_provider(self, request: ProviderRequest) -> ModelProvider:
        model = resolve_model(request.model_alias, self._model_catalogue)
        provider = self._providers.get(model.provider)
        if provider is None:
            raise ProviderError(
                f"No provider adapter is registered for provider {model.provider.value!r} "
                f"(model_alias {model.model_alias!r}).",
                category=ProviderErrorCategory.PERMANENT,
            )
        return provider
