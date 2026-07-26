from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import LatencyPreference, QualityTier
from domain.money import Money
from domain.policy import RoutingPolicy


class RoutingRequirements(BaseModel):
    """The caller's *requested* routing constraints.

    Treated as a request to satisfy, not an authoritative instruction — the applicable
    `RoutingPolicy` determines which of these the caller may actually set (ADR-010,
    `docs/requirements.md` FR-2.1). See `resolve_effective_requirements`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    quality_tier: QualityTier | None = None
    maximum_estimated_cost_usd: Money | None = None
    maximum_output_tokens: int | None = Field(default=None, gt=0)
    latency_preference: LatencyPreference | None = None
    requires_tool_use: bool = False
    requires_structured_output: bool = False


@dataclass(frozen=True)
class EffectiveRoutingRequirements:
    """The actual constraints applied to a request: requested, then policy-bounded.

    Unlike `RoutingRequirements`, every field here is fully resolved — `quality_tier`,
    `maximum_estimated_cost_usd`, `maximum_output_tokens`, and `latency_preference` are
    never `None`, because a `RoutingPolicy` always supplies a default for each.
    """

    capability: str
    quality_tier: QualityTier
    maximum_estimated_cost_usd: Decimal
    maximum_output_tokens: int
    latency_preference: LatencyPreference
    requires_tool_use: bool
    requires_structured_output: bool


def resolve_effective_requirements(
    requested: RoutingRequirements, policy: RoutingPolicy
) -> EffectiveRoutingRequirements:
    """Merge requested requirements with policy defaults and override permissions.

    For each overridable field, the client's value is used only if the policy
    permits an override for that field *and* the client supplied one; even then, cost
    and token overrides can only tighten the policy's own ceiling, never loosen it.
    Whether the requested capability itself is permitted is validated separately by
    the caller (see `application.route_evaluation_service`), not here.
    """
    overrides = policy.allow_client_overrides

    if (
        overrides.quality_tier
        and requested.quality_tier is not None
        and requested.quality_tier in policy.allowed_quality_tiers
    ):
        quality_tier = requested.quality_tier
    else:
        quality_tier = policy.default_quality_tier

    if overrides.maximum_estimated_cost_usd and requested.maximum_estimated_cost_usd is not None:
        cost_limit = min(requested.maximum_estimated_cost_usd, policy.maximum_estimated_cost_usd)
    else:
        cost_limit = policy.maximum_estimated_cost_usd

    if overrides.maximum_output_tokens and requested.maximum_output_tokens is not None:
        token_limit = min(requested.maximum_output_tokens, policy.maximum_output_tokens)
    else:
        token_limit = policy.maximum_output_tokens

    if overrides.latency_preference and requested.latency_preference is not None:
        latency_preference = requested.latency_preference
    else:
        latency_preference = policy.latency_preference

    return EffectiveRoutingRequirements(
        capability=requested.capability,
        quality_tier=quality_tier,
        maximum_estimated_cost_usd=cost_limit,
        maximum_output_tokens=token_limit,
        latency_preference=latency_preference,
        requires_tool_use=requested.requires_tool_use,
        requires_structured_output=requested.requires_structured_output,
    )
