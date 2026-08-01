"""Unit tests for `BedrockModelProvider` using a hand-rolled fake client.

A fake (rather than `botocore.stub.Stubber`) is used here because several scenarios
(malformed responses, missing usage) need response shapes Stubber's strict service-model
validation would reject even though they're exactly what a real, buggy/unexpected
response could look like. `tests/contract/test_bedrock_provider_stubber.py` covers the
same provider using a real, Stubber-wrapped boto3 client for realistic request/response
validation.
"""

from collections.abc import Sequence
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from adapters.bedrock.bedrock_model_provider import BedrockModelProvider
from adapters.common.retry import RetryPolicy
from domain.enums import ProviderErrorCategory, Role
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest
from tests.support.fakes import InMemoryModelCatalogue, make_model

pytestmark = pytest.mark.unit


class FakeBedrockRuntimeClient:
    """Returns/raises each item in `responses`, in order, one per `.converse()` call."""

    def __init__(self, responses: Sequence[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeBedrockRuntimeClient: no more responses configured")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "irrelevant"}}, "Converse")


def _valid_response(text: str = "hello there") -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 5, "outputTokens": 7},
    }


def _request(**overrides: Any) -> ProviderRequest:
    defaults: dict[str, Any] = {
        "model_alias": "balanced-text-primary",
        "messages": (Message(role=Role.USER, content="hi"),),
        "max_output_tokens": 100,
    }
    defaults.update(overrides)
    return ProviderRequest(**defaults)


def _provider(
    client: FakeBedrockRuntimeClient,
    *,
    models=None,
    retry_policy: RetryPolicy | None = None,
    sleep_calls: list[float] | None = None,
) -> BedrockModelProvider:
    catalogue = InMemoryModelCatalogue(
        models
        if models is not None
        else [make_model("balanced-text-primary", capability_tags=("balanced-text",))]
    )
    recorded = sleep_calls if sleep_calls is not None else []
    return BedrockModelProvider(
        client=client,  # type: ignore[arg-type]
        model_catalogue=catalogue,
        retry_policy=retry_policy,
        sleep=recorded.append,
        jitter=lambda: 0.0,
    )


def test_successful_invocation() -> None:
    client = FakeBedrockRuntimeClient([_valid_response("hello there")])
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert response.usage.input_tokens == 5
    assert len(client.calls) == 1


def test_malformed_provider_response_raises_permanent_error_without_retry() -> None:
    raw = _valid_response()
    del raw["output"]
    client = FakeBedrockRuntimeClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert len(client.calls) == 1


def test_missing_usage_information_raises_permanent_error() -> None:
    raw = _valid_response()
    del raw["usage"]
    client = FakeBedrockRuntimeClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_throttling_retries_then_succeeds() -> None:
    client = FakeBedrockRuntimeClient(
        [
            _client_error("ThrottlingException"),
            _client_error("ThrottlingException"),
            _valid_response(),
        ]
    )
    sleep_calls: list[float] = []
    provider = _provider(client, sleep_calls=sleep_calls)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 3
    assert len(sleep_calls) == 2


def test_throttling_exhausts_retries_and_raises() -> None:
    client = FakeBedrockRuntimeClient([_client_error("ThrottlingException")] * 3)
    sleep_calls: list[float] = []
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3), sleep_calls=sleep_calls)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.THROTTLED
    assert len(client.calls) == 3
    assert len(sleep_calls) == 2


def test_transient_provider_failure_retries_then_succeeds() -> None:
    client = FakeBedrockRuntimeClient(
        [_client_error("ServiceUnavailableException"), _valid_response()]
    )
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 2


def test_permanent_provider_failure_raises_immediately_without_retry() -> None:
    client = FakeBedrockRuntimeClient([_client_error("ValidationException")])
    sleep_calls: list[float] = []
    provider = _provider(client, sleep_calls=sleep_calls)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert len(client.calls) == 1
    assert sleep_calls == []


def test_timeout_retries_then_succeeds() -> None:
    client = FakeBedrockRuntimeClient(
        [ConnectTimeoutError(endpoint_url="https://example.invalid"), _valid_response()]
    )
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 2


def test_timeout_exhausts_retries_and_raises() -> None:
    client = FakeBedrockRuntimeClient(
        [ConnectTimeoutError(endpoint_url="https://example.invalid")] * 3
    )
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.TIMEOUT


def test_invalid_model_alias_raises_without_calling_client() -> None:
    client = FakeBedrockRuntimeClient([_valid_response()])
    provider = _provider(client, models=[])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(model_alias="does-not-exist"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.calls == []


def test_unsupported_parameter_mapping_raises_without_calling_client() -> None:
    client = FakeBedrockRuntimeClient([_valid_response()])
    model = make_model(
        "balanced-text-primary", capability_tags=("balanced-text",), supports_tool_use=False
    )
    provider = _provider(client, models=[model])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(requires_tool_use=True))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.calls == []


def test_unsupported_structured_output_raises_without_calling_client() -> None:
    client = FakeBedrockRuntimeClient([_valid_response()])
    model = make_model(
        "balanced-text-primary",
        capability_tags=("balanced-text",),
        supports_structured_output=False,
    )
    provider = _provider(client, models=[model])

    with pytest.raises(ProviderError):
        provider.invoke(_request(requires_structured_output=True))

    assert client.calls == []


def test_exceptions_never_leak_prompt_content() -> None:
    secret = "MY-VERY-SECRET-PROMPT-CONTENT"
    client = FakeBedrockRuntimeClient([_client_error("ThrottlingException")] * 3)
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(messages=(Message(role=Role.USER, content=secret),)))

    assert secret not in str(exc_info.value)


def test_malformed_response_exception_never_leaks_response_content() -> None:
    secret = "TOP-SECRET-MODEL-OUTPUT"
    raw = _valid_response(secret)
    del raw["usage"]
    client = FakeBedrockRuntimeClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert secret not in str(exc_info.value)


def test_router_alias_resolves_one_hop() -> None:
    from domain.catalogue import ModelResolution
    from domain.enums import ModelResolutionType

    target = make_model("real-model", capability_tags=("balanced-text",))
    alias_model = target.model_copy(
        update={
            "model_alias": "router-alias-model",
            "resolution": ModelResolution(
                type=ModelResolutionType.ROUTER_ALIAS, value="real-model"
            ),
        }
    )
    client = FakeBedrockRuntimeClient([_valid_response()])
    provider = _provider(client, models=[target, alias_model])

    provider.invoke(_request(model_alias="router-alias-model"))

    assert client.calls[0]["modelId"] == target.resolution.value


def test_router_alias_pointing_to_another_router_alias_is_rejected() -> None:
    from domain.catalogue import ModelResolution
    from domain.enums import ModelResolutionType

    base = make_model("base-model", capability_tags=("balanced-text",))
    alias_a = base.model_copy(
        update={
            "model_alias": "alias-a",
            "resolution": ModelResolution(type=ModelResolutionType.ROUTER_ALIAS, value="alias-b"),
        }
    )
    alias_b = base.model_copy(
        update={
            "model_alias": "alias-b",
            "resolution": ModelResolution(
                type=ModelResolutionType.ROUTER_ALIAS, value="base-model"
            ),
        }
    )
    client = FakeBedrockRuntimeClient([_valid_response()])
    provider = _provider(client, models=[base, alias_a, alias_b])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(model_alias="alias-a"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.calls == []
