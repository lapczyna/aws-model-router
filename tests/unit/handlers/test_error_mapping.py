from datetime import UTC, datetime
from decimal import Decimal

import pytest

from domain.candidates import RouteCandidate
from domain.decision import RoutingDecision
from domain.enums import ProviderErrorCategory, ProviderName
from domain.errors import (
    ConfigurationError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    ProviderError,
    RoutingPolicyNotFoundError,
)
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage
from handlers.error_mapping import (
    map_exception_to_status_and_body,
    map_no_selection_to_status_and_body,
)
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (RoutingPolicyNotFoundError("no policy"), 403, "POLICY_DENIED"),
        (IdempotencyConflictError("conflict"), 409, "IDEMPOTENCY_CONFLICT"),
        (IdempotencyInProgressError("in progress"), 409, "IDEMPOTENCY_IN_PROGRESS"),
        (ConfigurationError("bad config"), 500, "INTERNAL_ERROR"),
        (
            ProviderError("provider down", category=ProviderErrorCategory.PERMANENT),
            502,
            "PROVIDER_UNAVAILABLE",
        ),
        (ValueError("totally unexpected"), 500, "INTERNAL_ERROR"),
    ],
)
def test_map_exception_to_status_and_body(exception, expected_status, expected_code) -> None:
    status, body = map_exception_to_status_and_body(exception, "req-1")

    assert status == expected_status
    assert body["errorCode"] == expected_code
    assert body["requestId"] == "req-1"
    assert "message" in body


def test_map_exception_never_leaks_original_exception_text() -> None:
    secret = "arn:aws:secretsmanager:us-east-1:123456789012:secret:super-secret-value"
    _status, body = map_exception_to_status_and_body(ConfigurationError(secret), "req-1")
    assert secret not in body["message"]


def _candidate(
    model_alias: str, eligible: bool, reason_codes: tuple[RoutingReasonCode, ...]
) -> RouteCandidate:
    return RouteCandidate(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        eligible=eligible,
        reason_codes=reason_codes,
        estimated_usage=Usage(input_tokens=1, output_tokens=1),
        estimated_cost=EstimatedCost(amount_usd=Decimal("1.0")),
    )


def _decision(
    reason_codes: tuple[RoutingReasonCode, ...],
    considered_candidates: tuple[RouteCandidate, ...] = (),
) -> RoutingDecision:
    return RoutingDecision(
        decision_id="dec_1",
        application_id="app-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        policy_id=make_policy().policy_id,
        policy_version=1,
        capability="balanced-text",
        selected_model_alias=None,
        provider=None,
        reason_codes=reason_codes,
        considered_candidates=considered_candidates,
    )


def test_invocation_attempted_and_exhausted_maps_to_provider_unavailable() -> None:
    decision = _decision((RoutingReasonCode.MODEL_THROTTLED,))
    status, body = map_no_selection_to_status_and_body(
        decision, invocation_attempted=True, request_id="req-1"
    )
    assert status == 502
    assert body["errorCode"] == "PROVIDER_UNAVAILABLE"


def test_required_capability_unavailable_maps_to_422() -> None:
    decision = _decision((RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE,))
    status, body = map_no_selection_to_status_and_body(
        decision, invocation_attempted=False, request_id="req-1"
    )
    assert status == 422
    assert body["errorCode"] == "REQUIRED_CAPABILITY_UNAVAILABLE"


def test_all_candidates_cost_rejected_maps_to_402() -> None:
    candidates = (
        _candidate("model-a", False, (RoutingReasonCode.COST_LIMIT_EXCEEDED,)),
        _candidate("model-b", False, (RoutingReasonCode.COST_LIMIT_EXCEEDED,)),
    )
    decision = _decision((RoutingReasonCode.NO_ELIGIBLE_MODEL,), candidates)
    status, body = map_no_selection_to_status_and_body(
        decision, invocation_attempted=False, request_id="req-1"
    )
    assert status == 402
    assert body["errorCode"] == "COST_LIMIT_EXCEEDED"


def test_generic_no_eligible_model_maps_to_404() -> None:
    candidates = (_candidate("model-a", False, (RoutingReasonCode.MODEL_NOT_ALLOWED,)),)
    decision = _decision((RoutingReasonCode.NO_ELIGIBLE_MODEL,), candidates)
    status, body = map_no_selection_to_status_and_body(
        decision, invocation_attempted=False, request_id="req-1"
    )
    assert status == 404
    assert body["errorCode"] == "NO_ELIGIBLE_MODEL"


def test_no_candidates_at_all_maps_to_404() -> None:
    decision = _decision((RoutingReasonCode.NO_ELIGIBLE_MODEL,), ())
    status, body = map_no_selection_to_status_and_body(
        decision, invocation_attempted=False, request_id="req-1"
    )
    assert status == 404
    assert body["errorCode"] == "NO_ELIGIBLE_MODEL"
