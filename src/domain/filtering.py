"""Candidate model filtering: capability, allowlist, quality tier, token, and cost.

Every filter dimension is evaluated for every candidate — even once one dimension has
already excluded it — so `RouteCandidate.reason_codes` fully explains an exclusion
instead of stopping at the first failure. There are no negative reason codes for a
capability or quality-tier mismatch (the fixed reason-code vocabulary only pairs
positive/negative codes for the allowlist, token-limit, and cost-limit dimensions);
for those two dimensions, the *absence* of the corresponding positive code (paired with
`eligible=False`) is the signal.
"""

from collections.abc import Sequence

from domain.candidates import RouteCandidate
from domain.catalogue import ModelDefinition
from domain.enums import ModelHealthStatus
from domain.messages import Message
from domain.policy import RoutingPolicy
from domain.ports import CostEstimator, ModelHealthRepository, TokenEstimator
from domain.reason_codes import RoutingReasonCode, sort_reason_codes
from domain.requirements import EffectiveRoutingRequirements


def evaluate_candidate(
    model: ModelDefinition,
    requirements: EffectiveRoutingRequirements,
    policy: RoutingPolicy,
    token_estimator: TokenEstimator,
    cost_estimator: CostEstimator,
    messages: Sequence[Message],
    health_status: ModelHealthStatus = ModelHealthStatus.HEALTHY,
) -> RouteCandidate:
    reason_codes: list[RoutingReasonCode] = []
    eligible = True

    if health_status is ModelHealthStatus.UNAVAILABLE:
        reason_codes.append(RoutingReasonCode.MODEL_UNHEALTHY)
        eligible = False
    elif health_status is ModelHealthStatus.DEGRADED:
        # Informational only (ADR-020): a degraded model stays eligible — there is no
        # healthier alternative signal here beyond "this model has recently had trouble"
        # — but the decision's reason codes surface it for audit/dashboard visibility.
        reason_codes.append(RoutingReasonCode.MODEL_DEGRADED)

    capability_matched = (
        requirements.capability in model.capabilities.capability_tags
        and (not requirements.requires_tool_use or model.capabilities.supports_tool_use)
        and (
            not requirements.requires_structured_output
            or model.capabilities.supports_structured_output
        )
    )
    if capability_matched:
        reason_codes.append(RoutingReasonCode.CAPABILITY_MATCH)
    else:
        eligible = False

    if model.model_alias in policy.allowed_model_aliases:
        reason_codes.append(RoutingReasonCode.MODEL_ALLOWED)
    else:
        reason_codes.append(RoutingReasonCode.MODEL_NOT_ALLOWED)
        eligible = False

    if model.capabilities.quality_tier == requirements.quality_tier:
        reason_codes.append(RoutingReasonCode.QUALITY_TIER_MATCH)
    else:
        eligible = False

    usage = token_estimator.estimate(messages, requirements.maximum_output_tokens)
    if (
        usage.input_tokens > model.capabilities.max_input_tokens
        or usage.output_tokens > model.capabilities.max_output_tokens
    ):
        reason_codes.append(RoutingReasonCode.TOKEN_LIMIT_EXCEEDED)
        eligible = False

    estimated_cost = cost_estimator.estimate(usage, model.pricing)
    if estimated_cost.amount_usd <= requirements.maximum_estimated_cost_usd:
        reason_codes.append(RoutingReasonCode.WITHIN_COST_LIMIT)
    else:
        reason_codes.append(RoutingReasonCode.COST_LIMIT_EXCEEDED)
        eligible = False

    return RouteCandidate(
        model_alias=model.model_alias,
        provider=model.provider,
        eligible=eligible,
        reason_codes=tuple(sort_reason_codes(reason_codes)),
        estimated_usage=usage,
        estimated_cost=estimated_cost,
    )


def build_route_candidates(
    models: Sequence[ModelDefinition],
    requirements: EffectiveRoutingRequirements,
    policy: RoutingPolicy,
    token_estimator: TokenEstimator,
    cost_estimator: CostEstimator,
    messages: Sequence[Message],
    model_health_repository: ModelHealthRepository | None = None,
) -> list[RouteCandidate]:
    return [
        evaluate_candidate(
            model,
            requirements,
            policy,
            token_estimator,
            cost_estimator,
            messages,
            health_status=(
                model_health_repository.get_health(model.model_alias)
                if model_health_repository is not None
                else ModelHealthStatus.HEALTHY
            ),
        )
        for model in models
    ]
