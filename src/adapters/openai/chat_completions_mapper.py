"""Maps between `domain.provider` models and OpenAI's Chat Completions API wire shape.

This is the one place that understands Chat Completions' request/response structure —
everything above it (routing, invocation orchestration) only ever sees
`ProviderRequest`/`ProviderResponse` (ADR-009, extended to a second provider by
ADR-029). Kept as pure functions, independent of the `openai` client, so mapping logic
is unit-testable without a network call.
"""

from collections.abc import Iterable, Iterator
from typing import Any

from openai.types.chat import ChatCompletion, ChatCompletionChunk

from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk
from domain.usage import Usage

_FINISH_REASON_MAP: dict[str, StopReason] = {
    "stop": StopReason.END_TURN,
    "length": StopReason.MAX_TOKENS,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,  # legacy name for the same concept
    "content_filter": StopReason.CONTENT_FILTERED,
}

_MALFORMED_RESPONSE_MESSAGE = "The model provider returned a malformed response."


def map_finish_reason(raw: str) -> StopReason:
    """Map a raw Chat Completions `finish_reason` value to `StopReason`.

    Unrecognized values map to `StopReason.OTHER` rather than raising — OpenAI may add
    new finish reasons over time, and an unrecognized-but-valid reason should never fail
    response parsing (mirrors `adapters.bedrock.converse_mapper.map_stop_reason`).
    """
    return _FINISH_REASON_MAP.get(raw, StopReason.OTHER)


def build_chat_completion_request(request: ProviderRequest, target_model: str) -> dict[str, Any]:
    """Build the keyword arguments for `client.chat.completions.create(**kwargs)`.

    OpenAI has no separate top-level "system" field like Bedrock's Converse API — a
    system prompt is just another message, conventionally first in the list.
    """
    messages: list[dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": Role.SYSTEM.value, "content": request.system_prompt})
    messages.extend(
        {"role": message.role.value, "content": message.content} for message in request.messages
    )

    payload: dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "max_tokens": request.max_output_tokens,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    return payload


def build_chat_completion_stream_request(
    request: ProviderRequest, target_model: str
) -> dict[str, Any]:
    """Build the keyword arguments for `client.chat.completions.create(stream=True,
    **kwargs)` (ADR-032, Phase 10c) -- the same payload as `build_chat_completion_request`
    plus `stream=True` and `stream_options={"include_usage": True}`, the latter being
    what makes the Chat Completions API emit a final usage-only chunk; without it, a
    streamed response never reports token usage at all.
    """
    payload = build_chat_completion_request(request, target_model)
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}
    return payload


def parse_chat_completion_response(
    response: ChatCompletion, model_alias: str, provider: ProviderName
) -> ProviderResponse:
    """Parse an OpenAI `ChatCompletion` response into a `ProviderResponse`.

    Raises `ProviderError` (category `PERMANENT`) if required fields are missing or
    malformed — covers both a genuinely malformed response shape and a response missing
    usage information, since both mean the response cannot be normalized safely.
    """
    try:
        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason_raw = choice.finish_reason
        usage = response.usage
    except IndexError as exc:
        raise ProviderError(
            _MALFORMED_RESPONSE_MESSAGE, category=ProviderErrorCategory.PERMANENT
        ) from exc
    if usage is None:
        # OpenAI omitted usage information -- the response cannot be normalized safely.
        raise ProviderError(_MALFORMED_RESPONSE_MESSAGE, category=ProviderErrorCategory.PERMANENT)
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens

    return ProviderResponse(
        model_alias=model_alias,
        provider=provider,
        message=Message(role=Role.ASSISTANT, content=content),
        stop_reason=map_finish_reason(finish_reason_raw),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def iter_chat_completion_stream_chunks(
    chunks: Iterable[ChatCompletionChunk],
) -> Iterator[ProviderResponseChunk]:
    """Convert a raw Chat Completions stream (an iterable of `ChatCompletionChunk`) into
    `ProviderResponseChunk`s (ADR-032, Phase 10c).

    Mirrors `adapters.bedrock.converse_mapper.iter_converse_stream_events`: incremental
    `delta.content` text is yielded as it arrives, and the finish reason/usage totals --
    carried by different chunks (`stream_options={"include_usage": True}` puts usage on
    its own final, choice-less chunk) -- are folded into one final chunk
    (`is_final=True`) once the stream is exhausted.

    Raises `ProviderError` (category `PERMANENT`) if the stream ends without ever
    supplying a finish reason or usage. Errors raised by the `openai` SDK while iterating
    `chunks` are deliberately left unhandled here for `OpenAIModelProvider` to classify
    with the same `classify_provider_exception` it already uses for `.create()`.
    """
    finish_reason_raw: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    for chunk in chunks:
        if chunk.choices:
            choice = chunk.choices[0]
            if choice.delta.content:
                yield ProviderResponseChunk(delta_text=choice.delta.content)
            if choice.finish_reason is not None:
                finish_reason_raw = choice.finish_reason
        if chunk.usage is not None:
            input_tokens = chunk.usage.prompt_tokens
            output_tokens = chunk.usage.completion_tokens

    if finish_reason_raw is None or input_tokens is None or output_tokens is None:
        raise ProviderError(_MALFORMED_RESPONSE_MESSAGE, category=ProviderErrorCategory.PERMANENT)

    yield ProviderResponseChunk(
        is_final=True,
        stop_reason=map_finish_reason(finish_reason_raw),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )
