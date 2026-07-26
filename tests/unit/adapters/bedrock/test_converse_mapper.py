from typing import Any

import pytest

from adapters.bedrock.converse_mapper import (
    build_converse_request,
    map_stop_reason,
    parse_converse_response,
)
from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest

pytestmark = pytest.mark.unit


def test_build_converse_request_minimal() -> None:
    request = ProviderRequest(
        model_alias="balanced-text-primary",
        messages=(Message(role=Role.USER, content="hello"),),
        max_output_tokens=100,
    )

    payload = build_converse_request(request, "anthropic.claude-3-5-sonnet-20240620-v1:0")

    assert payload["modelId"] == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert payload["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]
    assert payload["inferenceConfig"] == {"maxTokens": 100}
    assert "system" not in payload


def test_build_converse_request_includes_optional_fields() -> None:
    request = ProviderRequest(
        model_alias="balanced-text-primary",
        messages=(Message(role=Role.USER, content="hello"),),
        system_prompt="be concise",
        max_output_tokens=100,
        temperature=0.3,
        top_p=0.8,
    )

    payload = build_converse_request(request, "model-id")

    assert payload["system"] == [{"text": "be concise"}]
    assert payload["inferenceConfig"] == {"maxTokens": 100, "temperature": 0.3, "topP": 0.8}


def test_build_converse_request_maps_multiple_messages_in_order() -> None:
    request = ProviderRequest(
        model_alias="balanced-text-primary",
        messages=(
            Message(role=Role.USER, content="first"),
            Message(role=Role.ASSISTANT, content="second"),
            Message(role=Role.USER, content="third"),
        ),
        max_output_tokens=100,
    )

    payload = build_converse_request(request, "model-id")

    assert [m["role"] for m in payload["messages"]] == ["user", "assistant", "user"]
    assert [m["content"][0]["text"] for m in payload["messages"]] == ["first", "second", "third"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("end_turn", StopReason.END_TURN),
        ("max_tokens", StopReason.MAX_TOKENS),
        ("stop_sequence", StopReason.STOP_SEQUENCE),
        ("tool_use", StopReason.TOOL_USE),
        ("content_filtered", StopReason.CONTENT_FILTERED),
        ("guardrail_intervened", StopReason.GUARDRAIL_INTERVENED),
        ("some_future_reason_we_do_not_know_about", StopReason.OTHER),
    ],
)
def test_map_stop_reason(raw: str, expected: StopReason) -> None:
    assert map_stop_reason(raw) is expected


def _valid_raw_response() -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "hello there"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 34},
    }


def test_parse_converse_response_success() -> None:
    response = parse_converse_response(
        _valid_raw_response(), "balanced-text-primary", ProviderName.BEDROCK
    )

    assert response.model_alias == "balanced-text-primary"
    assert response.provider is ProviderName.BEDROCK
    assert response.message.content == "hello there"
    assert response.stop_reason is StopReason.END_TURN
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 34


def test_parse_converse_response_concatenates_multiple_text_blocks() -> None:
    raw = _valid_raw_response()
    raw["output"]["message"]["content"] = [{"text": "hello "}, {"text": "there"}]

    response = parse_converse_response(raw, "model-a", ProviderName.BEDROCK)

    assert response.message.content == "hello there"


def test_parse_converse_response_missing_output_is_malformed() -> None:
    raw = _valid_raw_response()
    del raw["output"]

    with pytest.raises(ProviderError) as exc_info:
        parse_converse_response(raw, "model-a", ProviderName.BEDROCK)
    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_parse_converse_response_missing_usage_is_malformed() -> None:
    raw = _valid_raw_response()
    del raw["usage"]

    with pytest.raises(ProviderError) as exc_info:
        parse_converse_response(raw, "model-a", ProviderName.BEDROCK)
    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_parse_converse_response_incomplete_usage_is_malformed() -> None:
    raw = _valid_raw_response()
    del raw["usage"]["outputTokens"]

    with pytest.raises(ProviderError):
        parse_converse_response(raw, "model-a", ProviderName.BEDROCK)


def test_parse_converse_response_error_message_does_not_leak_response_content() -> None:
    raw = _valid_raw_response()
    raw["output"]["message"]["content"] = [{"text": "top secret prompt content"}]
    del raw["usage"]

    with pytest.raises(ProviderError) as exc_info:
        parse_converse_response(raw, "model-a", ProviderName.BEDROCK)

    assert "top secret prompt content" not in str(exc_info.value)
