"""Deterministic, explainable routing strategies (ADR-007).

Each strategy selects among the *already-eligible* candidates produced by
`domain.filtering.build_route_candidates` — none of them re-checks allowlist, token, or
cost eligibility. Given the same eligible candidate set and `RoutingContext`, a strategy
always returns the same selection; there is no randomness or hidden state.

Four strategies are defined: preferred-model, lowest-cost, and quality-tier (Phase 2),
and weighted-experiment (Phase 4, ADR-012). Latency-preference and fallback routing are
handled elsewhere — fallback is orthogonal to primary strategy selection entirely (it
operates at the invocation layer, see `application.invocation_orchestrator`), not
another `RoutingStrategy` choice.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from domain.candidates import RouteCandidate
from domain.enums import RoutingStrategyType
from domain.experiment import assign_experiment_cohort, build_experiment_subject_key
from domain.policy import RoutingPolicy
from domain.reason_codes import RoutingReasonCode
from domain.requirements import EffectiveRoutingRequirements


@dataclass(frozen=True)
class RoutingContext:
    """Per-request context a strategy may need beyond the candidate set and policy.

    A dataclass (not extra loose parameters) so a future strategy needing more context
    doesn't require another `RoutingStrategy.select()` signature change.
    """

    application_id: str
    conversation_id: str | None = None


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
        context: RoutingContext,
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
        context: RoutingContext,
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
        context: RoutingContext,
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
        context: RoutingContext,
    ) -> RouteSelection:
        if not eligible:
            return RouteSelection(selected=None)
        winner = min(eligible, key=lambda c: c.model_alias)
        return RouteSelection(selected=winner)


class ExperimentStrategy:
    """Selects the candidate deterministically assigned by the policy's experiment.

    The assigned arm is looked up in `eligible` by alias; if that specific arm isn't
    eligible (e.g. it failed a cost/token check for this request), this strategy does
    *not* silently reassign to a different arm — that would contaminate the experiment's
    statistical validity. It returns no selection, same as any other strategy exhausting
    its eligible set.

    Note (added Phase 9, ADR-028): this guarantee is about *this strategy's own*
    behavior, not the orchestrator's separate fallback mechanism. If a policy combines
    `routing_strategy: experiment` with a non-empty `fallback_policy`, and the assigned
    arm becomes ineligible (e.g. health-excluded), `InvocationOrchestrator` can still
    invoke a configured fallback model instead — but never silently: `fallback_used` and
    `FALLBACK_SELECTED` are always set on the resulting decision, so experiment analysis
    that requires strict arm purity should filter on `fallback_used`, the same as any
    other auditable substitution in this system. No shipped sample policy currently
    combines `experiment` with a configured `fallback_policy` (`experimental-app.yaml`
    has none).
    """

    def select(
        self,
        eligible: Sequence[RouteCandidate],
        policy: RoutingPolicy,
        requirements: EffectiveRoutingRequirements,
        context: RoutingContext,
    ) -> RouteSelection:
        experiment = policy.experiment_policy
        if experiment is None:
            return RouteSelection(selected=None)

        subject_key = build_experiment_subject_key(
            experiment, context.application_id, context.conversation_id
        )
        assigned_alias = assign_experiment_cohort(subject_key, experiment)

        for candidate in eligible:
            if candidate.model_alias == assigned_alias:
                return RouteSelection(
                    selected=candidate,
                    additional_reason_codes=(RoutingReasonCode.EXPERIMENT_ROUTE_SELECTED,),
                )
        return RouteSelection(selected=None)


_STRATEGIES: dict[RoutingStrategyType, RoutingStrategy] = {
    RoutingStrategyType.PREFERRED_MODEL: PreferredModelStrategy(),
    RoutingStrategyType.LOWEST_COST: LowestCostStrategy(),
    RoutingStrategyType.QUALITY_TIER: QualityTierStrategy(),
    RoutingStrategyType.EXPERIMENT: ExperimentStrategy(),
}


def get_strategy(strategy_type: RoutingStrategyType) -> RoutingStrategy:
    """Return the `RoutingStrategy` implementation for a `RoutingStrategyType`."""
    return _STRATEGIES[strategy_type]
