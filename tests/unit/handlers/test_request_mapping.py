from datetime import UTC, datetime
from decimal import Decimal

import pytest

from domain.decision import RoutingDecision
from domain.enums import LatencyPreference, ProviderName, QualityTier, Role, StopReason
from domain.invocation import (
    AuditRecord,
    InferenceResult,
    InvocationAttempt,
    InvocationAttemptStatus,
)
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage
from handlers.request_mapping import (
    parse_inference_request,
    parse_json_body,
    serialize_audit_record,
    serialize_inference_result,
    serialize_models_response,
    serialize_route_evaluation,
)
from tests.support.fakes import make_model, make_policy

pytestmark = pytest.mark.unit


def test_parse_json_body_parses_numbers_as_decimal_not_float() -> None:
    body = parse_json_body('{"maximumEstimatedCostUsd": 0.01, "count": 3}')
    assert body["maximumEstimatedCostUsd"] == Decimal("0.01")
    assert isinstance(body["maximumEstimatedCostUsd"], Decimal)
    assert body["count"] == 3
    assert isinstance(body["count"], int)


def test_parse_inference_request_full_payload() -> None:
    body = parse_json_body("""
        {
            "applicationId": "support-assistant",
            "messages": [{"role": "user", "content": "hello"}],
            "requirements": {
                "capability": "balanced-text",
                "qualityTier": "premium",
                "maximumEstimatedCostUsd": 0.02,
                "maximumOutputTokens": 500,
                "latencyPreference": "low",
                "requiresToolUse": true,
                "requiresStructuredOutput": false
            },
            "conversationId": "conv-1",
            "idempotencyKey": "key-1",
            "metadata": {"useCase": "incident-summary"}
        }
        """)

    request = parse_inference_request(body)

    assert request.application_id == "support-assistant"
    assert request.messages[0].role is Role.USER
    assert request.messages[0].content == "hello"
    assert request.requirements.capability == "balanced-text"
    assert request.requirements.quality_tier is QualityTier.PREMIUM
    assert request.requirements.latency_preference is LatencyPreference.LOW
    assert request.requirements.maximum_estimated_cost_usd == Decimal("0.02")
    assert request.requirements.maximum_output_tokens == 500
    assert request.requirements.requires_tool_use is True
    assert request.requirements.requires_structured_output is False
    assert request.conversation_id == "conv-1"
    assert request.idempotency_key == "key-1"
    assert request.metadata == {"useCase": "incident-summary"}


def test_parse_inference_request_minimal_payload() -> None:
    body = parse_json_body(
        '{"applicationId": "app-1", "messages": [{"role": "user", "content": "hi"}], '
        '"requirements": {"capability": "balanced-text"}}'
    )
    request = parse_inference_request(body)

    assert request.conversation_id is None
    assert request.idempotency_key is None
    assert request.metadata == {}
    assert request.requirements.quality_tier is None


def test_parse_inference_request_missing_application_id_raises() -> None:
    body = parse_json_body(
        '{"messages": [{"role": "user", "content": "hi"}], '
        '"requirements": {"capability": "balanced-text"}}'
    )
    with pytest.raises(KeyError):
        parse_inference_request(body)


def _decision(**overrides: object) -> RoutingDecision:
    defaults: dict[str, object] = {
        "decision_id": "dec_1",
        "application_id": "app-1",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "policy_id": make_policy().policy_id,
        "policy_version": 1,
        "capability": "balanced-text",
        "selected_model_alias": "model-a",
        "provider": ProviderName.BEDROCK,
        "fallback_used": False,
        "reason_codes": (RoutingReasonCode.CAPABILITY_MATCH,),
        "considered_candidates": (),
        "estimated_usage": Usage(input_tokens=10, output_tokens=20),
        "estimated_cost": EstimatedCost(amount_usd=Decimal("0.0021")),
    }
    defaults.update(overrides)
    return RoutingDecision.model_validate(defaults)


def test_serialize_route_evaluation() -> None:
    decision = _decision()
    body = serialize_route_evaluation(decision, "req-1")

    assert body["decisionId"] == "dec_1"
    assert body["route"]["modelAlias"] == "model-a"
    assert body["route"]["provider"] == "bedrock"
    assert body["route"]["fallbackUsed"] is False
    assert body["route"]["reasonCodes"] == ["CAPABILITY_MATCH"]
    assert body["usageEstimate"] == {
        "inputTokens": 10,
        "outputTokens": 20,
        "estimatedCostUsd": 0.0021,
    }
    assert body["requestId"] == "req-1"
    assert body["consideredCandidates"] == []


def test_serialize_inference_result_with_response() -> None:
    decision = _decision()
    response = ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hello there"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=20),
    )
    result = InferenceResult(decision=decision, response=response, invocation_attempts=())

    body = serialize_inference_result(result, "req-1")

    assert body["decisionId"] == "dec_1"
    assert body["response"] == {"role": "assistant", "content": "hello there"}
    assert body["usage"]["estimatedCostUsd"] == 0.0021
    assert body["requestId"] == "req-1"


def test_serialize_inference_result_without_response() -> None:
    decision = _decision(
        selected_model_alias=None,
        provider=None,
        reason_codes=(RoutingReasonCode.NO_ELIGIBLE_MODEL,),
        estimated_usage=None,
        estimated_cost=None,
    )
    result = InferenceResult(decision=decision, response=None, invocation_attempts=())

    body = serialize_inference_result(result, "req-1")

    assert body["response"] is None
    assert body["usage"] is None
    assert body["route"]["modelAlias"] is None


def test_serialize_audit_record() -> None:
    decision = _decision()
    attempt = InvocationAttempt(
        model_alias="model-a", status=InvocationAttemptStatus.SUCCEEDED, latency_ms=123
    )
    audit_record = AuditRecord(decision=decision, invocation_attempts=(attempt,))

    body = serialize_audit_record(audit_record, "req-1")

    assert body["decisionId"] == "dec_1"
    assert body["applicationId"] == "app-1"
    assert body["createdAt"] == "2026-01-01T00:00:00Z"
    assert body["policyVersion"] == 1
    assert body["invocationAttempts"] == [
        {"modelAlias": "model-a", "status": "succeeded", "latencyMs": 123}
    ]


def test_serialize_models_response_groups_by_capability_and_picks_best_latency() -> None:
    fast_model = make_model(
        "fast",
        capability_tags=("balanced-text",),
        supports_tool_use=True,
        typical_latency=LatencyPreference.LOW,
    )
    slow_model = make_model(
        "slow",
        capability_tags=("balanced-text",),
        quality_tier=QualityTier.PREMIUM,
        typical_latency=LatencyPreference.HIGH,
    )

    body = serialize_models_response([fast_model, slow_model], "req-1")

    assert len(body["capabilities"]) == 1
    entry = body["capabilities"][0]
    assert entry["capability"] == "balanced-text"
    assert entry["typicalLatency"] == "low"  # best (lowest) of the group
    assert entry["supportsToolUse"] is True  # true for at least one model in the group
    assert sorted(entry["qualityTiers"]) == ["premium", "standard"]
    assert body["requestId"] == "req-1"
