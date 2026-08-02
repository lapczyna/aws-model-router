"""`EventBridgeDecisionEventPublisher`: publishes one sanitized event per completed
`POST /v1/inference` call to Amazon EventBridge (ADR-030), so an external system can
subscribe to routing decisions instead of polling `GET /v1/decisions/{decisionId}`.

Only metadata ever leaves this adapter — the same discipline as `AuditRecord` and
`EmfMetricsPublisher` (ADR-008): decision/policy identifiers, capability, selected
model, fallback/cost metadata, never raw prompt or response content.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from domain.invocation import InferenceResult

if TYPE_CHECKING:
    from mypy_boto3_events.client import EventBridgeClient

logger = logging.getLogger(__name__)

_SOURCE = "aws-model-router"
_DETAIL_TYPE = "RoutingDecisionCompleted"


class EventBridgeDecisionEventPublisher:
    def __init__(self, client: EventBridgeClient, event_bus_name: str) -> None:
        self._client = client
        self._event_bus_name = event_bus_name

    def publish(self, result: InferenceResult) -> None:
        detail = self._build_detail(result)
        try:
            self._client.put_events(
                Entries=[
                    {
                        "Source": _SOURCE,
                        "DetailType": _DETAIL_TYPE,
                        "EventBusName": self._event_bus_name,
                        "Detail": json.dumps(detail),
                    }
                ]
            )
        except Exception:
            # Best-effort, per domain.ports.DecisionEventPublisher's contract: a
            # failure to publish a decision event must never fail the underlying
            # request. Logged for operator visibility, never re-raised.
            logger.exception(
                "Failed to publish decision event to EventBridge",
                extra={"decision_id": result.decision.decision_id},
            )

    @staticmethod
    def _build_detail(result: InferenceResult) -> dict[str, Any]:
        decision = result.decision
        return {
            "decisionId": decision.decision_id,
            "applicationId": decision.application_id,
            "createdAt": decision.created_at.isoformat(),
            "policyId": decision.policy_id,
            "policyVersion": decision.policy_version,
            "capability": decision.capability,
            "selectedModelAlias": decision.selected_model_alias,
            "provider": decision.provider.value if decision.provider is not None else None,
            "fallbackUsed": decision.fallback_used,
            "reasonCodes": [code.value for code in decision.reason_codes],
            "estimatedCostUsd": (
                float(decision.estimated_cost.amount_usd)
                if decision.estimated_cost is not None
                else None
            ),
        }
