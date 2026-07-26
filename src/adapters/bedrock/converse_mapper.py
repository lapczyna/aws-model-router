"""Maps between `domain.provider` models and the Bedrock Converse API's wire shape.

This is the one place that understands Converse's request/response JSON structure —
everything above it (routing, invocation orchestration) only ever sees
`ProviderRequest`/`ProviderResponse` (ADR-009). Kept as pure functions, independent of
the boto3 client, so mapping logic is unit-testable without a network call or Stubber.
"""

from collections.abc import Mapping
from typing import Any

from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse
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
    """Build the keyword arguments for `bedrock_runtime_client.converse(**kwargs)`.

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
