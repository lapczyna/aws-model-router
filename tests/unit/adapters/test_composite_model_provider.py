from collections.abc import Iterator

import pytest

from adapters.composite_model_provider import CompositeModelProvider
from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk
from domain.usage import Usage
from tests.support.fakes import InMemoryModelCatalogue, make_model

pytestmark = pytest.mark.unit


class _FakeSubProvider:
    def __init__(self, provider_name: ProviderName) -> None:
        self._provider_name = provider_name
        self.calls: list[str] = []

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request.model_alias)
        return ProviderResponse(
            model_alias=request.model_alias,
            provider=self._provider_name,
            message=Message(role=Role.ASSISTANT, content=f"handled by {self._provider_name.value}"),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=1, output_tokens=1),
        )


class _FakeStreamingSubProvider(_FakeSubProvider):
    """A sub-provider that additionally implements `StreamingModelProvider` -- unlike
    `_FakeSubProvider`, which deliberately only has `invoke`, so it can stand in for a
    provider adapter that hasn't (yet) implemented streaming."""

    def invoke_stream(self, request: ProviderRequest) -> Iterator[ProviderResponseChunk]:
        self.calls.append(request.model_alias)
        yield ProviderResponseChunk(delta_text=f"handled by {self._provider_name.value}")
        yield ProviderResponseChunk(
            is_final=True,
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=1, output_tokens=1),
        )


def _request(model_alias: str) -> ProviderRequest:
    return ProviderRequest(
        model_alias=model_alias,
        messages=(Message(role=Role.USER, content="hi"),),
        max_output_tokens=100,
    )


def test_dispatches_to_the_provider_matching_the_resolved_model() -> None:
    bedrock_model = make_model(
        "bedrock-model", provider=ProviderName.BEDROCK, capability_tags=("balanced-text",)
    )
    openai_model = make_model(
        "openai-model", provider=ProviderName.OPENAI, capability_tags=("balanced-text",)
    )
    catalogue = InMemoryModelCatalogue([bedrock_model, openai_model])
    bedrock_provider = _FakeSubProvider(ProviderName.BEDROCK)
    openai_provider = _FakeSubProvider(ProviderName.OPENAI)
    composite = CompositeModelProvider(
        model_catalogue=catalogue,
        providers={ProviderName.BEDROCK: bedrock_provider, ProviderName.OPENAI: openai_provider},
    )

    bedrock_response = composite.invoke(_request("bedrock-model"))
    openai_response = composite.invoke(_request("openai-model"))

    assert bedrock_response.message.content == "handled by bedrock"
    assert openai_response.message.content == "handled by openai"
    assert bedrock_provider.calls == ["bedrock-model"]
    assert openai_provider.calls == ["openai-model"]


def test_unknown_model_alias_raises_permanent_error_without_calling_any_provider() -> None:
    catalogue = InMemoryModelCatalogue([])
    bedrock_provider = _FakeSubProvider(ProviderName.BEDROCK)
    composite = CompositeModelProvider(
        model_catalogue=catalogue, providers={ProviderName.BEDROCK: bedrock_provider}
    )

    with pytest.raises(ProviderError) as exc_info:
        composite.invoke(_request("does-not-exist"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert bedrock_provider.calls == []


def test_model_with_unregistered_provider_raises_permanent_error() -> None:
    openai_model = make_model(
        "openai-model", provider=ProviderName.OPENAI, capability_tags=("balanced-text",)
    )
    catalogue = InMemoryModelCatalogue([openai_model])
    bedrock_provider = _FakeSubProvider(ProviderName.BEDROCK)
    # Only Bedrock is registered -- no OpenAI adapter configured.
    composite = CompositeModelProvider(
        model_catalogue=catalogue, providers={ProviderName.BEDROCK: bedrock_provider}
    )

    with pytest.raises(ProviderError) as exc_info:
        composite.invoke(_request("openai-model"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert "openai" in str(exc_info.value)
    assert bedrock_provider.calls == []


def test_empty_providers_mapping_raises_permanent_error_for_any_model() -> None:
    model = make_model("some-model", provider=ProviderName.BEDROCK)
    catalogue = InMemoryModelCatalogue([model])
    composite = CompositeModelProvider(model_catalogue=catalogue, providers={})

    with pytest.raises(ProviderError) as exc_info:
        composite.invoke(_request("some-model"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_invoke_stream_dispatches_to_the_provider_matching_the_resolved_model() -> None:
    model = make_model(
        "bedrock-model", provider=ProviderName.BEDROCK, capability_tags=("balanced-text",)
    )
    catalogue = InMemoryModelCatalogue([model])
    bedrock_provider = _FakeStreamingSubProvider(ProviderName.BEDROCK)
    composite = CompositeModelProvider(
        model_catalogue=catalogue, providers={ProviderName.BEDROCK: bedrock_provider}
    )

    chunks = list(composite.invoke_stream(_request("bedrock-model")))

    assert "".join(c.delta_text for c in chunks) == "handled by bedrock"
    assert bedrock_provider.calls == ["bedrock-model"]


def test_invoke_stream_unknown_model_alias_raises_without_calling_any_provider() -> None:
    catalogue = InMemoryModelCatalogue([])
    bedrock_provider = _FakeStreamingSubProvider(ProviderName.BEDROCK)
    composite = CompositeModelProvider(
        model_catalogue=catalogue, providers={ProviderName.BEDROCK: bedrock_provider}
    )

    with pytest.raises(ProviderError) as exc_info:
        composite.invoke_stream(_request("does-not-exist"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert bedrock_provider.calls == []


def test_invoke_stream_non_streaming_provider_raises_permanent_error() -> None:
    model = make_model(
        "bedrock-model", provider=ProviderName.BEDROCK, capability_tags=("balanced-text",)
    )
    catalogue = InMemoryModelCatalogue([model])
    # `_FakeSubProvider` only implements `invoke`, not `invoke_stream`.
    bedrock_provider = _FakeSubProvider(ProviderName.BEDROCK)
    composite = CompositeModelProvider(
        model_catalogue=catalogue, providers={ProviderName.BEDROCK: bedrock_provider}
    )

    with pytest.raises(ProviderError) as exc_info:
        composite.invoke_stream(_request("bedrock-model"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert "streaming" in str(exc_info.value)
    assert bedrock_provider.calls == []
