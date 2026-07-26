"""Deterministic, explainable routing strategies (ADR-007).

Each strategy selects among the *already-eligible* candidates produced by
`domain.filtering.build_route_candidates` — none of them re-checks allowlist, token, or
cost eligibility. Given the same eligible candidate set, a strategy always returns the
same selection; there is no randomness or hidden state.

Only the three strategies Phase 2 implements are defined here: preferred-model,
lowest-cost, and quality-tier. Latency-preference, weighted-experiment, and fallback
routing are added in later phases (see `PROJECT_PLAN.md`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from domain.candidates import RouteCandidate
from domain.enums import RoutingStrategyType
from domain.policy import RoutingPolicy
from domain.reason_codes import RoutingReasonCode
from domain.requirements import EffectiveRoutingRequirements


@dataclass(frozen=True)
class RouteSelection:
    selected: RouteCandidate | None
    additional_reason_codes: tuple[RoutingReasonCode, ...] = field(default=())


class RoutingStrategy(Protocol):
    def select(
        self,
        eligible: Sequence[RouteCandidate],
        policy: RoutingPolicy,
        requirements: EffectiveRoutingRequirements,
    ) -> RouteSelection: ...


class PreferredModelStrategy:
    """Selects the policy's configured preferred model, if it is eligible.

    Never falls back to a different model when the preferred one is ineligible — that
    is the job of fallback routing (Phase 4), a distinct, explicitly policy-controlled
    behavior, not something this strategy does implicitly.
    """

    def select(
        self,
        eligible: Sequence[RouteCandidate],
        policy: RoutingPolicy,
        requirements: EffectiveRoutingRequirements,
    ) -> RouteSelection:
        for candidate in eligible:
            if candidate.model_alias == policy.preferred_model_alias:
                return RouteSelection(selected=candidate)
        return RouteSelection(selected=None)


class LowestCostStrategy:
    """Selects the lowest estimated-cost eligible candidate.

    Ties are broken by `model_alias` for full determinism.
    """

    def select(
        self,
        eligible: Sequence[RouteCandidate],
        policy: RoutingPolicy,
        requirements: EffectiveRoutingRequirements,
    ) -> RouteSelection:
        if not eligible:
            return RouteSelection(selected=None)
        winner = min(eligible, key=lambda c: (c.estimated_cost.amount_usd, c.model_alias))
        return RouteSelection(
            selected=winner, additional_reason_codes=(RoutingReasonCode.LOWEST_ESTIMATED_COST,)
        )


class QualityTierStrategy:
    """Selects among candidates that matched the effective quality tier.

    Ties are broken deterministically by `model_alias` (alphabetically), not by cost —
    this keeps the strategy's behavior distinct from `LowestCostStrategy` even though
    quality-tier matching itself is applied as a general filter for every strategy.
    """

    def select(
        self,
        eligible: Sequence[RouteCandidate],
        policy: RoutingPolicy,
        requirements: EffectiveRoutingRequirements,
    ) -> RouteSelection:
        if not eligible:
            return RouteSelection(selected=None)
        winner = min(eligible, key=lambda c: c.model_alias)
        return RouteSelection(selected=winner)


_STRATEGIES: dict[RoutingStrategyType, RoutingStrategy] = {
    RoutingStrategyType.PREFERRED_MODEL: PreferredModelStrategy(),
    RoutingStrategyType.LOWEST_COST: LowestCostStrategy(),
    RoutingStrategyType.QUALITY_TIER: QualityTierStrategy(),
}


def get_strategy(strategy_type: RoutingStrategyType) -> RoutingStrategy:
    """Return the `RoutingStrategy` implementation for a `RoutingStrategyType`."""
    return _STRATEGIES[strategy_type]
