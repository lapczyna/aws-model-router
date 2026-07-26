from datetime import UTC, datetime

import pytest

from domain.decision import RoutingDecision
from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.invocation import (
    AuditRecord,
    InferenceResult,
    InvocationAttempt,
    InvocationAttemptStatus,
    reason_code_for_provider_error_category,
    status_for_provider_error_category,
)
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import Usage
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("category", "expected_status"),
    [
        (ProviderErrorCategory.THROTTLED, InvocationAttemptStatus.THROTTLED),
        (ProviderErrorCategory.TRANSIENT, InvocationAttemptStatus.TRANSIENT_ERROR),
        (ProviderErrorCategory.TIMEOUT, InvocationAttemptStatus.TIMEOUT),
        (ProviderErrorCategory.PERMANENT, InvocationAttemptStatus.NON_RETRYABLE_ERROR),
    ],
)
def test_status_for_provider_error_category(category, expected_status) -> None:
    assert status_for_provider_error_category(category) is expected_status


@pytest.mark.parametrize(
    ("category", "expected_code"),
    [
        (ProviderErrorCategory.THROTTLED, RoutingReasonCode.MODEL_THROTTLED),
        (ProviderErrorCategory.TRANSIENT, RoutingReasonCode.MODEL_UNAVAILABLE),
        (ProviderErrorCategory.TIMEOUT, RoutingReasonCode.MODEL_UNAVAILABLE),
        (ProviderErrorCategory.PERMANENT, None),
    ],
)
def test_reason_code_for_provider_error_category(category, expected_code) -> None:
    assert reason_code_for_provider_error_category(category) == expected_code


def test_invocation_attempt_requires_non_negative_latency() -> None:
    attempt = InvocationAttempt(
        model_alias="model-a", status=InvocationAttemptStatus.SUCCEEDED, latency_ms=0
    )
    assert attempt.latency_ms == 0


def test_inference_result_and_audit_record_construction() -> None:
    decision = RoutingDecision(
        decision_id="dec_1",
        application_id="app-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        policy_id=make_policy().policy_id,
        policy_version=1,
        capability="balanced-text",
        selected_model_alias="model-a",
        provider=ProviderName.BEDROCK,
        reason_codes=(RoutingReasonCode.CAPABILITY_MATCH,),
        considered_candidates=(),
    )
    response = ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hi"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    attempt = InvocationAttempt(
        model_alias="model-a", status=InvocationAttemptStatus.SUCCEEDED, latency_ms=100
    )

    result = InferenceResult(decision=decision, response=response, invocation_attempts=(attempt,))
    audit_record = AuditRecord(decision=decision, invocation_attempts=(attempt,))

    assert result.response is not None
    assert result.response.message.content == "hi"
    assert audit_record.invocation_attempts == (attempt,)
