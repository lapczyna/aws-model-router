"""Tests `EventBridgeDecisionEventPublisher` against a hand-rolled fake EventBridge
client: the published event's `Detail` must be metadata only (ADR-008), and a client
failure must never propagate -- publishing a decision event is best-effort, per
`domain.ports.DecisionEventPublisher`'s contract.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from adapters.events.eventbridge_decision_event_publisher import (
    EventBridgeDecisionEventPublisher,
)
from domain.decision import RoutingDecision
from domain.enums import ProviderName, Role, StopReason
from domain.invocation import InferenceResult
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage

pytestmark = pytest.mark.unit


class _FakeEventBridgeClient:
    def __init__(self, raise_on_put: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raise_on_put = raise_on_put

    def put_events(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raise_on_put is not None:
            raise self._raise_on_put
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "evt-1"}]}


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


def _result(**decision_overrides: object) -> InferenceResult:
    return InferenceResult(
        decision=_decision(**decision_overrides), response=None, invocation_attempts=()
    )


def test_publishes_one_entry_to_the_configured_bus() -> None:
    client = _FakeEventBridgeClient()
    publisher = EventBridgeDecisionEventPublisher(client=client, event_bus_name="my-bus")  # type: ignore[arg-type]

    publisher.publish(_result())

    assert len(client.calls) == 1
    entries = client.calls[0]["Entries"]
    assert len(entries) == 1
    assert entries[0]["EventBusName"] == "my-bus"
    assert entries[0]["Source"] == "aws-model-router"
    assert entries[0]["DetailType"] == "RoutingDecisionCompleted"


def test_detail_contains_only_sanitized_metadata_fields() -> None:
    client = _FakeEventBridgeClient()
    publisher = EventBridgeDecisionEventPublisher(client=client, event_bus_name="my-bus")  # type: ignore[arg-type]

    publisher.publish(_result())

    detail = json.loads(client.calls[0]["Entries"][0]["Detail"])
    assert detail == {
        "decisionId": "dec_1",
        "applicationId": "app-1",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "policyId": "test-policy",
        "policyVersion": 1,
        "capability": "balanced-text",
        "selectedModelAlias": "model-a",
        "provider": "bedrock",
        "fallbackUsed": False,
        "reasonCodes": ["CAPABILITY_MATCH"],
        "estimatedCostUsd": 0.0021,
    }


def test_detail_handles_no_selected_model_and_no_cost() -> None:
    client = _FakeEventBridgeClient()
    publisher = EventBridgeDecisionEventPublisher(client=client, event_bus_name="my-bus")  # type: ignore[arg-type]
    result = _result(
        selected_model_alias=None,
        provider=None,
        estimated_usage=None,
        estimated_cost=None,
        reason_codes=(RoutingReasonCode.NO_ELIGIBLE_MODEL,),
    )

    publisher.publish(result)

    detail = json.loads(client.calls[0]["Entries"][0]["Detail"])
    assert detail["selectedModelAlias"] is None
    assert detail["provider"] is None
    assert detail["estimatedCostUsd"] is None


def test_client_failure_is_swallowed_and_never_propagates() -> None:
    client = _FakeEventBridgeClient(raise_on_put=RuntimeError("EventBridge is down"))
    publisher = EventBridgeDecisionEventPublisher(client=client, event_bus_name="my-bus")  # type: ignore[arg-type]

    publisher.publish(_result())  # must not raise

    assert len(client.calls) == 1


def test_never_includes_raw_response_content() -> None:
    """`_build_detail` only ever reads fields off `result.decision` -- proving it never
    reads `result.response` (where any real model output would live) by constructing a
    result whose response contains a distinctive secret and confirming it never appears
    in the published detail."""
    client = _FakeEventBridgeClient()
    publisher = EventBridgeDecisionEventPublisher(client=client, event_bus_name="my-bus")  # type: ignore[arg-type]
    secret = "TOP-SECRET-MODEL-OUTPUT"
    result = InferenceResult(
        decision=_decision(),
        response=ProviderResponse(
            model_alias="model-a",
            provider=ProviderName.BEDROCK,
            message=Message(role=Role.ASSISTANT, content=secret),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=20),
        ),
        invocation_attempts=(),
    )

    publisher.publish(result)

    raw_detail = client.calls[0]["Entries"][0]["Detail"]
    assert secret not in raw_detail
