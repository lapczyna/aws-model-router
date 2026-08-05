"""Maps between `domain.provider` models and the Bedrock Converse API's wire shape.

This is the one place that understands Converse's request/response JSON structure —
everything above it (routing, invocation orchestration) only ever sees
`ProviderRequest`/`ProviderResponse` (ADR-009). Kept as pure functions, independent of
the boto3 client, so mapping logic is unit-testable without a network call or Stubber.
"""

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk
from domain.usage import Usage

_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "tool_use": StopReason.TOOL_USE,
    "content_filtered": StopReason.CONTENT_FILTERED,
    "guardrail_intervened": StopReason.GUARDRAIL_INTERVENED,
}

_MALFORMED_RESPONSE_MESSAGE = "The model provider returned a malformed response."


def map_stop_reason(raw: str) -> StopReason:
    """Map a raw Converse `stopReason` value to `StopReason`.

    Unrecognized values map to `StopReason.OTHER` rather than raising — Bedrock may add
    new stop reasons over time, and an unrecognized-but-valid reason should never fail
    response parsing.
    """
    return _STOP_REASON_MAP.get(raw, StopReason.OTHER)


def build_converse_request(request: ProviderRequest, target_model_id: str) -> dict[str, Any]:
    """Build the keyword arguments for `bedrock_runtime_client.converse(**kwargs)` --
    also reused as-is for `.converse_stream(**kwargs)` (ADR-032, Phase 10c): Bedrock's
    Converse and ConverseStream APIs share an identical request shape, differing only in
    how the response comes back.

    Inference parameters (`maxTokens`, `temperature`, `topP`) are part of Converse's own
    unified `inferenceConfig` and are supported uniformly across Converse-compatible
    models (ADR-009) — per-model variance that actually matters (tool use, structured
    output) is validated separately, against `ModelCapabilities`, before this function
    is ever called (see `BedrockModelProvider._check_capabilities`).
    """
    inference_config: dict[str, Any] = {"maxTokens": request.max_output_tokens}
    if request.temperature is not None:
        inference_config["temperature"] = request.temperature
    if request.top_p is not None:
        inference_config["topP"] = request.top_p

    payload: dict[str, Any] = {
        "modelId": target_model_id,
        "messages": [
            {"role": message.role.value, "content": [{"text": message.content}]}
            for message in request.messages
        ],
        "inferenceConfig": inference_config,
    }
    if request.system_prompt:
        payload["system"] = [{"text": request.system_prompt}]
    return payload


def parse_converse_response(
    raw: Mapping[str, Any], model_alias: str, provider: ProviderName
) -> ProviderResponse:
    """Parse a raw Converse API response into a `ProviderResponse`.

    Raises `ProviderError` (category `PERMANENT`) if required fields are missing or
    malformed — covers both a genuinely malformed response shape and a response missing
    usage information, since both mean the response cannot be normalized safely.
    """
    try:
        message_raw = raw["output"]["message"]
        content_blocks = message_raw["content"]
        text = "".join(block["text"] for block in content_blocks if "text" in block)
        stop_reason_raw = raw["stopReason"]
        usage_raw = raw["usage"]
        input_tokens = usage_raw["inputTokens"]
        output_tokens = usage_raw["outputTokens"]
    except (KeyError, TypeError) as exc:
        raise ProviderError(
            _MALFORMED_RESPONSE_MESSAGE, category=ProviderErrorCategory.PERMANENT
        ) from exc

    return ProviderResponse(
        model_alias=model_alias,
        provider=provider,
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=map_stop_reason(stop_reason_raw),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def iter_converse_stream_events(
    events: Iterable[Mapping[str, Any]],
) -> Iterator[ProviderResponseChunk]:
    """Convert a raw `ConverseStream` event stream into `ProviderResponseChunk`s
    (ADR-032, Phase 10c).

    Each `contentBlockDelta` event yields one chunk carrying its incremental text.
    `messageStop`/`metadata` events carry no text of their own -- they only supply the
    stop reason and usage totals folded into the one final chunk (`is_final=True`)
    yielded once the underlying stream is exhausted, mirroring `parse_converse_response`
    building a single `ProviderResponse` from the equivalent non-streaming fields.

    Raises `ProviderError` (category `PERMANENT`) if the stream ends without ever
    supplying a stop reason or usage -- same "cannot normalize safely" rule
    `parse_converse_response` applies to a malformed non-streaming response. Service-side
    stream errors (e.g. `ModelStreamErrorException`) surface as `ClientError`/
    `BotoCoreError` raised by botocore while iterating `events`, deliberately left
    unhandled here for `BedrockModelProvider` to classify with the same
    `classify_provider_exception` it already uses for `.converse()`.
    """
    stop_reason_raw: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    for event in events:
        if "contentBlockDelta" in event:
            text = event["contentBlockDelta"].get("delta", {}).get("text")
            if text:
                yield ProviderResponseChunk(delta_text=text)
        elif "messageStop" in event:
            stop_reason_raw = event["messageStop"]["stopReason"]
        elif "metadata" in event:
            usage_raw = event["metadata"].get("usage")
            if usage_raw is not None:
                input_tokens = usage_raw["inputTokens"]
                output_tokens = usage_raw["outputTokens"]

    if stop_reason_raw is None or input_tokens is None or output_tokens is None:
        raise ProviderError(_MALFORMED_RESPONSE_MESSAGE, category=ProviderErrorCategory.PERMANENT)

    yield ProviderResponseChunk(
        is_final=True,
        stop_reason=map_stop_reason(stop_reason_raw),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )
