import pytest
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage

from adapters.openai.chat_completions_mapper import (
    build_chat_completion_stream_request,
    iter_chat_completion_stream_chunks,
    map_finish_reason,
)
from domain.enums import ProviderErrorCategory, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest

pytestmark = pytest.mark.unit


def test_build_chat_completion_stream_request_enables_streaming_and_usage() -> None:
    request = ProviderRequest(
        model_alias="openai-balanced-text",
        messages=(Message(role=Role.USER, content="hi"),),
        max_output_tokens=100,
    )

    payload = build_chat_completion_stream_request(request, "gpt-4o-mini")

    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["model"] == "gpt-4o-mini"


def _content_chunk(text: str, finish_reason: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chatcmpl-fake",
        object="chat.completion.chunk",
        created=0,
        model="gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(content=text),
                finish_reason=finish_reason,  # type: ignore[arg-type]
            )
        ],
    )


def _usage_only_chunk(prompt_tokens: int = 5, completion_tokens: int = 7) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chatcmpl-fake",
        object="chat.completion.chunk",
        created=0,
        model="gpt-4o-mini",
        choices=[],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def test_iter_chat_completion_stream_chunks_yields_deltas_then_final_chunk() -> None:
    chunks = list(
        iter_chat_completion_stream_chunks(
            [
                _content_chunk("hello "),
                _content_chunk("there", finish_reason="stop"),
                _usage_only_chunk(),
            ]
        )
    )

    assert [c.delta_text for c in chunks[:2]] == ["hello ", "there"]
    assert all(not c.is_final for c in chunks[:2])
    assert chunks[-1].is_final is True
    assert chunks[-1].stop_reason is StopReason.END_TURN
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.input_tokens == 5
    assert chunks[-1].usage.output_tokens == 7


def test_iter_chat_completion_stream_chunks_reconstructs_full_text() -> None:
    chunks = list(
        iter_chat_completion_stream_chunks(
            [
                _content_chunk("hello "),
                _content_chunk("there", finish_reason="stop"),
                _usage_only_chunk(),
            ]
        )
    )

    assert "".join(c.delta_text for c in chunks) == "hello there"


def test_iter_chat_completion_stream_chunks_ignores_empty_deltas() -> None:
    chunks = list(
        iter_chat_completion_stream_chunks(
            [_content_chunk(None, finish_reason="stop"), _usage_only_chunk()]  # type: ignore[arg-type]
        )
    )

    assert len(chunks) == 1
    assert chunks[0].is_final is True


def test_iter_chat_completion_stream_chunks_missing_finish_reason_is_malformed() -> None:
    with pytest.raises(ProviderError) as exc_info:
        list(iter_chat_completion_stream_chunks([_content_chunk("hi"), _usage_only_chunk()]))
    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_iter_chat_completion_stream_chunks_missing_usage_is_malformed() -> None:
    with pytest.raises(ProviderError) as exc_info:
        list(
            iter_chat_completion_stream_chunks(
                [_content_chunk("hi", finish_reason="stop")]
            )
        )
    assert exc_info.value.category is ProviderErrorCategory.PERMANENT


def test_iter_chat_completion_stream_chunks_error_never_leaks_response_content() -> None:
    with pytest.raises(ProviderError) as exc_info:
        list(
            iter_chat_completion_stream_chunks(
                [_content_chunk("TOP-SECRET-MODEL-OUTPUT")]
            )
        )
    assert "TOP-SECRET-MODEL-OUTPUT" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", StopReason.END_TURN),
        ("length", StopReason.MAX_TOKENS),
        ("tool_calls", StopReason.TOOL_USE),
        ("content_filter", StopReason.CONTENT_FILTERED),
    ],
)
def test_iter_chat_completion_stream_chunks_maps_finish_reason(
    raw: str, expected: StopReason
) -> None:
    chunks = list(
        iter_chat_completion_stream_chunks(
            [_content_chunk("hi", finish_reason=raw), _usage_only_chunk()]
        )
    )

    assert chunks[-1].stop_reason is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", StopReason.END_TURN),
        ("length", StopReason.MAX_TOKENS),
        ("tool_calls", StopReason.TOOL_USE),
        ("function_call", StopReason.TOOL_USE),
        ("content_filter", StopReason.CONTENT_FILTERED),
        ("some_future_reason_we_do_not_know_about", StopReason.OTHER),
    ],
)
def test_map_finish_reason(raw: str, expected: StopReason) -> None:
    assert map_finish_reason(raw) is expected
