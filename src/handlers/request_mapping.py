"""Maps between the public, camelCase HTTP JSON contract (`docs/architecture/api-
contracts.md`) and the internal, snake_case domain models — the translation boundary
anticipated since Phase 1 (`PROJECT_PLAN.md`'s "Domain model field casing" note).

Parsing request bodies always uses `json.loads(text, parse_float=Decimal)`: a JSON
number like `0.01` would otherwise become a Python `float`, which `domain.money.Money`
explicitly rejects (binary floats are unacceptable for monetary values) — parsing it
directly as `Decimal` from the wire text avoids ever constructing a lossy float at all.
Serializing responses converts `Decimal` back to `float` only at this presentation
boundary (`json.dumps` has no native `Decimal` support, and the documented API contract
represents cost as a JSON number, not a string) — never during business logic.
"""

import json
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from domain.candidates import RouteCandidate
from domain.catalogue import ModelDefinition
from domain.decision import RoutingDecision
from domain.enums import LatencyPreference, QualityTier, Role
from domain.invocation import AuditRecord, InferenceResult
from domain.messages import Message
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements

_LATENCY_RANK = {
    LatencyPreference.LOW: 0,
    LatencyPreference.BALANCED: 1,
    LatencyPreference.HIGH: 2,
}


def parse_json_body(raw_body: str) -> dict[str, Any]:
    return json.loads(raw_body, parse_float=Decimal)  # type: ignore[no-any-return]


def parse_inference_request(body: dict[str, Any]) -> InferenceRequest:
    requirements_raw = body.get("requirements") or {}
    quality_tier = requirements_raw.get("qualityTier")
    latency_preference = requirements_raw.get("latencyPreference")

    requirements = RoutingRequirements(
        capability=requirements_raw["capability"],
        quality_tier=QualityTier(quality_tier) if quality_tier is not None else None,
        maximum_estimated_cost_usd=requirements_raw.get("maximumEstimatedCostUsd"),
        maximum_output_tokens=requirements_raw.get("maximumOutputTokens"),
        latency_preference=(
            LatencyPreference(latency_preference) if latency_preference is not None else None
        ),
        requires_tool_use=requirements_raw.get("requiresToolUse", False),
        requires_structured_output=requirements_raw.get("requiresStructuredOutput", False),
    )
    messages = tuple(
        Message(role=Role(message["role"]), content=message["content"])
        for message in body["messages"]
    )
    return InferenceRequest(
        application_id=body["applicationId"],
        messages=messages,
        requirements=requirements,
        conversation_id=body.get("conversationId"),
        idempotency_key=body.get("idempotencyKey"),
        metadata=body.get("metadata") or {},
    )


def _serialize_route(decision: RoutingDecision) -> dict[str, Any]:
    return {
        "modelAlias": decision.selected_model_alias,
        "provider": decision.provider.value if decision.provider else None,
        "fallbackUsed": decision.fallback_used,
        "reasonCodes": [code.value for code in decision.reason_codes],
    }


def _serialize_usage(decision: RoutingDecision) -> dict[str, Any] | None:
    if decision.estimated_usage is None or decision.estimated_cost is None:
        return None
    return {
        "inputTokens": decision.estimated_usage.input_tokens,
        "outputTokens": decision.estimated_usage.output_tokens,
        "estimatedCostUsd": float(decision.estimated_cost.amount_usd),
    }


def _serialize_considered_candidate(
    candidate: RouteCandidate, selected_alias: str | None
) -> dict[str, Any]:
    return {
        "modelAlias": candidate.model_alias,
        "selected": candidate.model_alias == selected_alias,
        "estimatedCostUsd": float(candidate.estimated_cost.amount_usd),
        "reasonCodes": [code.value for code in candidate.reason_codes],
    }


def serialize_inference_result(result: InferenceResult, request_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "decisionId": result.decision.decision_id,
        "response": (
            {"role": result.response.message.role.value, "content": result.response.message.content}
            if result.response is not None
            else None
        ),
        "route": _serialize_route(result.decision),
        "usage": _serialize_usage(result.decision),
        "requestId": request_id,
    }
    return body


def serialize_route_evaluation(decision: RoutingDecision, request_id: str) -> dict[str, Any]:
    return {
        "decisionId": decision.decision_id,
        "route": _serialize_route(decision),
        "consideredCandidates": [
            _serialize_considered_candidate(candidate, decision.selected_model_alias)
            for candidate in decision.considered_candidates
        ],
        "usageEstimate": _serialize_usage(decision),
        "requestId": request_id,
    }


def serialize_audit_record(audit_record: AuditRecord, request_id: str) -> dict[str, Any]:
    decision = audit_record.decision
    return {
        "decisionId": decision.decision_id,
        "applicationId": decision.application_id,
        "createdAt": decision.created_at.isoformat().replace("+00:00", "Z"),
        "policyId": decision.policy_id,
        "policyVersion": decision.policy_version,
        "capability": decision.capability,
        "route": _serialize_route(decision),
        "usage": _serialize_usage(decision),
        "invocationAttempts": [
            {
                "modelAlias": attempt.model_alias,
                "status": attempt.status.value,
                "latencyMs": attempt.latency_ms,
            }
            for attempt in audit_record.invocation_attempts
        ],
        "requestId": request_id,
    }


def serialize_models_response(models: Sequence[ModelDefinition], request_id: str) -> dict[str, Any]:
    """Build the sanitized `GET /v1/models` response: aggregated, per-capability
    information only — never a raw model alias, provider model ID, or pricing detail.
    """
    by_capability: dict[str, list[ModelDefinition]] = defaultdict(list)
    for model in models:
        for tag in model.capabilities.capability_tags:
            by_capability[tag].append(model)

    capabilities = []
    for capability, group in sorted(by_capability.items()):
        quality_tiers = sorted({m.capabilities.quality_tier.value for m in group})
        best_latency = min(
            (m.capabilities.typical_latency for m in group),
            key=lambda latency: _LATENCY_RANK[latency],
        )
        capabilities.append(
            {
                "capability": capability,
                "qualityTiers": quality_tiers,
                "supportsToolUse": any(m.capabilities.supports_tool_use for m in group),
                "supportsStructuredOutput": any(
                    m.capabilities.supports_structured_output for m in group
                ),
                "typicalLatency": best_latency.value,
            }
        )

    return {"capabilities": capabilities, "requestId": request_id}
