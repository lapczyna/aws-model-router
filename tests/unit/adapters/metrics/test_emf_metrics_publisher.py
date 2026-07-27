"""Tests `EmfMetricsPublisher` against captured stdout: every printed line must be a
valid CloudWatch Embedded Metric Format (EMF) JSON object, declare exactly the
`Environment` CloudWatch dimension (ADR-019), and never carry a disallowed property
(`docs/requirements.md` NFR-4.2).
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from adapters.metrics.emf_metrics_publisher import EmfMetricsPublisher
from domain.decision import RoutingDecision
from domain.enums import ProviderName, Role, StopReason
from domain.invocation import InferenceResult, InvocationAttempt, InvocationAttemptStatus
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage

pytestmark = pytest.mark.unit


def _decision(**overrides: object) -> RoutingDecision:
    defaults: dict[str, object] = {
        "decision_id": "dec_1",
        "application_id": "app-1",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "policy_id": "test-policy",
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


def _response() -> ProviderResponse:
    return ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hi"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=20),
    )


def _emf_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_every_emitted_line_declares_only_environment_as_cloudwatch_dimension(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decision = _decision()
    result = InferenceResult(decision=decision, response=_response(), invocation_attempts=())
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    assert len(lines) > 0
    for line in lines:
        directive = line["_aws"]["CloudWatchMetrics"][0]
        assert directive["Dimensions"] == [["Environment"]]
        assert line["Environment"] == "dev"


def test_request_count_and_fallback_and_no_eligible_are_always_emitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decision = _decision(fallback_used=True)
    result = InferenceResult(decision=decision, response=_response(), invocation_attempts=())
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    metric_values = {
        line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"]: line
        for line in lines
        if "Capability" in line and "ModelAlias" not in line
    }
    assert metric_values["RequestCount"]["RequestCount"] == 1
    assert metric_values["FallbackUsedCount"]["FallbackUsedCount"] == 1
    assert metric_values["NoEligibleModelCount"]["NoEligibleModelCount"] == 0


def test_no_eligible_model_count_true_when_reason_code_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decision = _decision(
        selected_model_alias=None,
        provider=None,
        reason_codes=(RoutingReasonCode.NO_ELIGIBLE_MODEL,),
        estimated_usage=None,
        estimated_cost=None,
    )
    result = InferenceResult(decision=decision, response=None, invocation_attempts=())
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    no_eligible_lines = [
        line
        for line in lines
        if line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "NoEligibleModelCount"
    ]
    assert len(no_eligible_lines) == 1
    assert no_eligible_lines[0]["NoEligibleModelCount"] == 1


def test_estimated_cost_only_emitted_when_present(capsys: pytest.CaptureFixture[str]) -> None:
    decision = _decision(
        selected_model_alias=None,
        provider=None,
        reason_codes=(RoutingReasonCode.NO_ELIGIBLE_MODEL,),
        estimated_usage=None,
        estimated_cost=None,
    )
    result = InferenceResult(decision=decision, response=None, invocation_attempts=())
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    assert not any(
        line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "EstimatedCostUsd"
        for line in lines
    )


def test_estimated_cost_carries_application_id_as_extra_property(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decision = _decision()
    result = InferenceResult(decision=decision, response=_response(), invocation_attempts=())
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    cost_lines = [
        line
        for line in lines
        if line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "EstimatedCostUsd"
    ]
    assert len(cost_lines) == 1
    assert cost_lines[0]["ApplicationId"] == "app-1"
    assert cost_lines[0]["EstimatedCostUsd"] == pytest.approx(0.0021)


def test_per_attempt_metrics_include_provider_failure_only_for_non_succeeded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decision = _decision()
    attempts = (
        InvocationAttempt(
            model_alias="primary", status=InvocationAttemptStatus.THROTTLED, latency_ms=50
        ),
        InvocationAttempt(
            model_alias="fallback", status=InvocationAttemptStatus.SUCCEEDED, latency_ms=120
        ),
    )
    result = InferenceResult(decision=decision, response=_response(), invocation_attempts=attempts)
    EmfMetricsPublisher(environment="dev").publish(result)

    lines = _emf_lines(capsys)
    provider_failure_lines = [
        line
        for line in lines
        if line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "ProviderFailureCount"
    ]
    assert len(provider_failure_lines) == 1
    assert provider_failure_lines[0]["ModelAlias"] == "primary"
    assert provider_failure_lines[0]["Status"] == "throttled"

    attempt_count_lines = [
        line
        for line in lines
        if line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "InvocationAttemptCount"
    ]
    assert len(attempt_count_lines) == 2

    latency_lines = [
        line
        for line in lines
        if line["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "InvocationLatencyMs"
    ]
    assert {line["ModelAlias"]: line["InvocationLatencyMs"] for line in latency_lines} == {
        "primary": 50,
        "fallback": 120,
    }


def test_put_metric_rejects_disallowed_extra_key() -> None:
    publisher = EmfMetricsPublisher(environment="dev")
    with pytest.raises(ValueError, match="RequestId"):
        publisher._put_metric("SomeMetric", 1, "Count", {"RequestId": "req-1"})
