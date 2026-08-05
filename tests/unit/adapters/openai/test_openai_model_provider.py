"""Unit tests for `OpenAIModelProvider` using a hand-rolled fake client that mimics
`openai.OpenAI`'s `.chat.completions.create(...)` shape, constructing real `openai` SDK
response/exception objects rather than raw dicts — this exercises the actual response
parsing/exception-classification logic against real SDK types, the same spirit as
`tests/contract/test_bedrock_provider_stubber.py` using a real, wrapped boto3 client.
"""

from collections.abc import Sequence
from typing import Any

import httpx
import openai
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice
from openai.types.chat.chat_completion_chunk import ChoiceDelta
from openai.types.completion_usage import CompletionUsage

from adapters.common.retry import RetryPolicy
from adapters.openai.openai_model_provider import OpenAIModelProvider
from domain.enums import ProviderErrorCategory, ProviderName, Role
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest
from tests.support.fakes import InMemoryModelCatalogue, make_model

pytestmark = pytest.mark.unit

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


class _FakeCompletions:
    """Returns/raises each item in `responses`, in order, one per `.create()` call.
    A `stream=True` call is dispatched against its own separate `stream_responses`
    queue, mirroring how `FakeBedrockRuntimeClient` separates `.converse()` from
    `.converse_stream()`."""

    def __init__(
        self, responses: Sequence[Any] = (), stream_responses: Sequence[Any] = ()
    ) -> None:
        self._responses = list(responses)
        self._stream_responses = list(stream_responses)
        self.calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            self.stream_calls.append(kwargs)
            if not self._stream_responses:
                raise AssertionError("_FakeCompletions: no more stream responses configured")
            item = self._stream_responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("_FakeCompletions: no more responses configured")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeOpenAIClient:
    """Mimics `openai.OpenAI`'s `.chat.completions.create(...)` attribute path."""

    def __init__(
        self, responses: Sequence[Any] = (), stream_responses: Sequence[Any] = ()
    ) -> None:
        self._completions = _FakeCompletions(responses, stream_responses)
        self.chat = type("_Chat", (), {"completions": self._completions})()

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._completions.calls

    @property
    def stream_calls(self) -> list[dict[str, Any]]:
        return self._completions.stream_calls


def _status_error(cls: type[openai.APIStatusError], status_code: int) -> openai.APIStatusError:
    response = httpx.Response(status_code, request=_FAKE_REQUEST)
    return cls(f"status {status_code}", response=response, body=None)


def _valid_response(text: str = "hello there") -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-fake",
        object="chat.completion",
        created=0,
        model="gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=text),
            )
        ],
        usage=CompletionUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
    )


def _stream_chunks(text: str = "hello there") -> list[ChatCompletionChunk]:
    return [
        ChatCompletionChunk(
            id="chatcmpl-fake",
            object="chat.completion.chunk",
            created=0,
            model="gpt-4o-mini",
            choices=[
                ChunkChoice(index=0, delta=ChoiceDelta(content=text), finish_reason="stop")
            ],
        ),
        ChatCompletionChunk(
            id="chatcmpl-fake",
            object="chat.completion.chunk",
            created=0,
            model="gpt-4o-mini",
            choices=[],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
        ),
    ]


class _ChunksThenRaise:
    """A one-shot iterable that yields `chunks` then raises `exc` -- simulates a Chat
    Completions stream that fails partway through, mirroring
    `test_bedrock_model_provider._EventsThenRaise`."""

    def __init__(self, chunks: Sequence[Any], exc: Exception) -> None:
        self._chunks = list(chunks)
        self._exc = exc

    def __iter__(self) -> Any:
        yield from self._chunks
        raise self._exc


def _request(**overrides: Any) -> ProviderRequest:
    defaults: dict[str, Any] = {
        "model_alias": "openai-balanced-text",
        "messages": (Message(role=Role.USER, content="hi"),),
        "max_output_tokens": 100,
    }
    defaults.update(overrides)
    return ProviderRequest(**defaults)


def _provider(
    client: FakeOpenAIClient,
    *,
    models: list[Any] | None = None,
    retry_policy: RetryPolicy | None = None,
    sleep_calls: list[float] | None = None,
) -> OpenAIModelProvider:
    catalogue = InMemoryModelCatalogue(
        models
        if models is not None
        else [
            make_model(
                "openai-balanced-text",
                provider=ProviderName.OPENAI,
                capability_tags=("balanced-text",),
            )
        ]
    )
    recorded = sleep_calls if sleep_calls is not None else []
    return OpenAIModelProvider(
        client=client,  # type: ignore[arg-type]
        model_catalogue=catalogue,
        retry_policy=retry_policy,
        sleep=recorded.append,
        jitter=lambda: 0.0,
    )


def test_successful_invocation() -> None:
    client = FakeOpenAIClient([_valid_response("hello there")])
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 7
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "fake.openai-balanced-text-v1:0"


def test_malformed_provider_response_raises_permanent_error_without_retry() -> None:
    raw = _valid_response()
    raw.choices = []
    client = FakeOpenAIClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert len(client.calls) == 1


def test_missing_usage_information_raises_permanent_error() -> None:
    raw = _valid_response()
    raw.usage = None
    client = FakeOpenAIClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_rate_limit_retries_then_succeeds() -> None:
    client = FakeOpenAIClient(
        [
            _status_error(openai.RateLimitError, 429),
            _status_error(openai.RateLimitError, 429),
            _valid_response(),
        ]
    )
    sleep_calls: list[float] = []
    provider = _provider(client, sleep_calls=sleep_calls)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 3
    assert len(sleep_calls) == 2


def test_rate_limit_exhausts_retries_and_raises() -> None:
    client = FakeOpenAIClient([_status_error(openai.RateLimitError, 429)] * 3)
    sleep_calls: list[float] = []
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3), sleep_calls=sleep_calls)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.THROTTLED
    assert len(client.calls) == 3
    assert len(sleep_calls) == 2


def test_internal_server_error_retries_then_succeeds() -> None:
    client = FakeOpenAIClient([_status_error(openai.InternalServerError, 500), _valid_response()])
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 2


def test_connection_error_retries_then_succeeds() -> None:
    client = FakeOpenAIClient([openai.APIConnectionError(request=_FAKE_REQUEST), _valid_response()])
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 2


def test_timeout_retries_then_succeeds() -> None:
    client = FakeOpenAIClient([openai.APITimeoutError(request=_FAKE_REQUEST), _valid_response()])
    provider = _provider(client)

    response = provider.invoke(_request())

    assert response.message.content == "hello there"
    assert len(client.calls) == 2


def test_timeout_exhausts_retries_and_raises() -> None:
    client = FakeOpenAIClient([openai.APITimeoutError(request=_FAKE_REQUEST)] * 3)
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.TIMEOUT


def test_bad_request_raises_immediately_without_retry() -> None:
    client = FakeOpenAIClient([_status_error(openai.BadRequestError, 400)])
    sleep_calls: list[float] = []
    provider = _provider(client, sleep_calls=sleep_calls)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert len(client.calls) == 1
    assert sleep_calls == []


def test_authentication_error_raises_permanent_without_retry() -> None:
    client = FakeOpenAIClient([_status_error(openai.AuthenticationError, 401)])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert len(client.calls) == 1


def test_invalid_model_alias_raises_without_calling_client() -> None:
    client = FakeOpenAIClient([_valid_response()])
    provider = _provider(client, models=[])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(model_alias="does-not-exist"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.calls == []


def test_unsupported_tool_use_raises_without_calling_client() -> None:
    client = FakeOpenAIClient([_valid_response()])
    model = make_model(
        "openai-balanced-text",
        provider=ProviderName.OPENAI,
        capability_tags=("balanced-text",),
        supports_tool_use=False,
    )
    provider = _provider(client, models=[model])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(requires_tool_use=True))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.calls == []


def test_exceptions_never_leak_prompt_content() -> None:
    secret = "MY-VERY-SECRET-PROMPT-CONTENT"
    client = FakeOpenAIClient([_status_error(openai.RateLimitError, 429)] * 3)
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request(messages=(Message(role=Role.USER, content=secret),)))

    assert secret not in str(exc_info.value)


def test_malformed_response_exception_never_leaks_response_content() -> None:
    secret = "TOP-SECRET-MODEL-OUTPUT"
    raw = _valid_response(secret)
    raw.usage = None
    client = FakeOpenAIClient([raw])
    provider = _provider(client)

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert secret not in str(exc_info.value)


def test_router_alias_resolves_one_hop() -> None:
    from domain.catalogue import ModelResolution
    from domain.enums import ModelResolutionType

    target = make_model(
        "real-openai-model", provider=ProviderName.OPENAI, capability_tags=("balanced-text",)
    )
    alias_model = target.model_copy(
        update={
            "model_alias": "router-alias-model",
            "resolution": ModelResolution(
                type=ModelResolutionType.ROUTER_ALIAS, value="real-openai-model"
            ),
        }
    )
    client = FakeOpenAIClient([_valid_response()])
    provider = _provider(client, models=[target, alias_model])

    provider.invoke(_request(model_alias="router-alias-model"))

    assert client.calls[0]["model"] == target.resolution.value


def test_system_prompt_becomes_leading_system_message() -> None:
    client = FakeOpenAIClient([_valid_response()])
    provider = _provider(client)

    provider.invoke(_request(system_prompt="be concise"))

    messages = client.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be concise"}
    assert messages[1] == {"role": "user", "content": "hi"}


def test_invoke_stream_yields_deltas_then_final_chunk() -> None:
    client = FakeOpenAIClient(stream_responses=[_stream_chunks("hello there")])
    provider = _provider(client)

    chunks = list(provider.invoke_stream(_request()))

    assert "".join(c.delta_text for c in chunks) == "hello there"
    assert chunks[-1].is_final is True
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.input_tokens == 5
    assert len(client.stream_calls) == 1
    assert client.stream_calls[0]["stream"] is True
    assert client.stream_calls[0]["stream_options"] == {"include_usage": True}


def test_invoke_stream_is_lazy_until_iterated() -> None:
    client = FakeOpenAIClient(stream_responses=[_stream_chunks()])
    provider = _provider(client)

    generator = provider.invoke_stream(_request())

    assert client.stream_calls == []
    list(generator)
    assert len(client.stream_calls) == 1


def test_invoke_stream_invalid_model_alias_raises_without_calling_client() -> None:
    client = FakeOpenAIClient()
    provider = _provider(client, models=[])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke_stream(_request(model_alias="does-not-exist"))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.stream_calls == []


def test_invoke_stream_rate_limit_retries_stream_start_then_succeeds() -> None:
    client = FakeOpenAIClient(
        stream_responses=[_status_error(openai.RateLimitError, 429), _stream_chunks()]
    )
    sleep_calls: list[float] = []
    provider = _provider(client, sleep_calls=sleep_calls)

    chunks = list(provider.invoke_stream(_request()))

    assert chunks[-1].is_final is True
    assert len(client.stream_calls) == 2
    assert len(sleep_calls) == 1


def test_invoke_stream_exhausts_retries_before_first_chunk() -> None:
    client = FakeOpenAIClient(stream_responses=[_status_error(openai.RateLimitError, 429)] * 3)
    provider = _provider(client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ProviderError) as exc_info:
        list(provider.invoke_stream(_request()))

    assert exc_info.value.category is ProviderErrorCategory.THROTTLED
    assert len(client.stream_calls) == 3


def test_invoke_stream_mid_stream_failure_is_not_retried() -> None:
    first_chunk = _stream_chunks("partial ")[0]
    chunks = _ChunksThenRaise([first_chunk], _status_error(openai.RateLimitError, 429))
    client = FakeOpenAIClient(stream_responses=[chunks])
    provider = _provider(client)

    generator = provider.invoke_stream(_request())
    first = next(generator)

    assert first.delta_text == "partial "
    with pytest.raises(ProviderError) as exc_info:
        next(generator)
    assert exc_info.value.category is ProviderErrorCategory.THROTTLED
    assert len(client.stream_calls) == 1


def test_invoke_stream_unsupported_tool_use_raises_without_calling_client() -> None:
    model = make_model(
        "openai-balanced-text",
        provider=ProviderName.OPENAI,
        capability_tags=("balanced-text",),
        supports_tool_use=False,
    )
    client = FakeOpenAIClient(stream_responses=[_stream_chunks()])
    provider = _provider(client, models=[model])

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke_stream(_request(requires_tool_use=True))

    assert exc_info.value.category is ProviderErrorCategory.PERMANENT
    assert client.stream_calls == []
