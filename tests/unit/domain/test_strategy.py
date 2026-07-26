import pytest

from domain.candidates import RouteCandidate
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import QualityTier, Role, RoutingStrategyType
from domain.filtering import evaluate_candidate
from domain.messages import Message
from domain.reason_codes import RoutingReasonCode
from domain.requirements import RoutingRequirements, resolve_effective_requirements
from domain.strategy import (
    LowestCostStrategy,
    PreferredModelStrategy,
    QualityTierStrategy,
    get_strategy,
)
from tests.support.fakes import make_model, make_policy

pytestmark = pytest.mark.unit

TOKEN_ESTIMATOR = DefaultTokenEstimator()
COST_ESTIMATOR = DefaultCostEstimator()
MESSAGES = (Message(role=Role.USER, content="hello there"),)


def _effective(policy):
    requested = RoutingRequirements(capability="balanced-text")
    return resolve_effective_requirements(requested, policy)


def _candidate(model, policy) -> RouteCandidate:
    effective = _effective(policy)
    return evaluate_candidate(model, effective, policy, TOKEN_ESTIMATOR, COST_ESTIMATOR, MESSAGES)


def test_get_strategy_returns_expected_implementation_for_each_type() -> None:
    assert isinstance(get_strategy(RoutingStrategyType.PREFERRED_MODEL), PreferredModelStrategy)
    assert isinstance(get_strategy(RoutingStrategyType.LOWEST_COST), LowestCostStrategy)
    assert isinstance(get_strategy(RoutingStrategyType.QUALITY_TIER), QualityTierStrategy)


def test_preferred_model_strategy_selects_configured_model() -> None:
    cheap = make_model(
        "cheap",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    preferred = make_model(
        "preferred",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="1.0",
        output_price_per_1k_tokens="1.0",
    )
    policy = make_policy(
        allowed_model_aliases=("cheap", "preferred"),
        routing_strategy="preferred_model",
        preferred_model_alias="preferred",
        maximum_estimated_cost_usd="100",
    )
    eligible = [_candidate(cheap, policy), _candidate(preferred, policy)]

    selection = PreferredModelStrategy().select(eligible, policy, _effective(policy))

    assert selection.selected is not None
    assert selection.selected.model_alias == "preferred"
    assert selection.additional_reason_codes == ()


def test_preferred_model_strategy_returns_none_when_preferred_not_eligible() -> None:
    other = make_model("other", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("other", "preferred"),
        routing_strategy="preferred_model",
        preferred_model_alias="preferred",
    )
    eligible = [_candidate(other, policy)]  # "preferred" never made it into the eligible set

    selection = PreferredModelStrategy().select(eligible, policy, _effective(policy))

    assert selection.selected is None


def test_lowest_cost_strategy_selects_cheapest_and_tags_reason_code() -> None:
    cheap = make_model(
        "cheap",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    expensive = make_model(
        "expensive",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="1.0",
        output_price_per_1k_tokens="1.0",
    )
    policy = make_policy(
        allowed_model_aliases=("cheap", "expensive"),
        routing_strategy="lowest_cost",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="100",
    )
    eligible = [_candidate(expensive, policy), _candidate(cheap, policy)]

    selection = LowestCostStrategy().select(eligible, policy, _effective(policy))

    assert selection.selected is not None
    assert selection.selected.model_alias == "cheap"
    assert selection.additional_reason_codes == (RoutingReasonCode.LOWEST_ESTIMATED_COST,)


def test_lowest_cost_strategy_breaks_ties_by_model_alias() -> None:
    model_b = make_model(
        "b-model",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.005",
        output_price_per_1k_tokens="0.005",
    )
    model_a = make_model(
        "a-model",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.005",
        output_price_per_1k_tokens="0.005",
    )
    policy = make_policy(
        allowed_model_aliases=("a-model", "b-model"),
        routing_strategy="lowest_cost",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="100",
    )
    eligible = [_candidate(model_b, policy), _candidate(model_a, policy)]

    selection = LowestCostStrategy().select(eligible, policy, _effective(policy))

    assert selection.selected is not None
    assert selection.selected.model_alias == "a-model"


def test_quality_tier_strategy_selects_only_among_tier_matched_candidates() -> None:
    standard_model = make_model(
        "standard-model", capability_tags=("balanced-text",), quality_tier=QualityTier.STANDARD
    )
    policy = make_policy(
        allowed_model_aliases=("standard-model", "premium-model"),
        allowed_quality_tiers=(QualityTier.STANDARD, QualityTier.PREMIUM),
        default_quality_tier=QualityTier.STANDARD,
        routing_strategy="quality_tier",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="100",
    )
    # Only the standard-tier candidate is eligible here; a premium candidate would have
    # eligible=False (quality-tier mismatch against the effective "standard" tier) and
    # be excluded from the eligible list before it ever reaches the strategy.
    eligible = [_candidate(standard_model, policy)]

    selection = QualityTierStrategy().select(eligible, policy, _effective(policy))

    assert selection.selected is not None
    assert selection.selected.model_alias == "standard-model"


def test_all_strategies_return_none_when_no_eligible_candidates() -> None:
    policy = make_policy(routing_strategy="preferred_model")
    effective = _effective(policy)
    assert PreferredModelStrategy().select([], policy, effective).selected is None
    assert LowestCostStrategy().select([], policy, effective).selected is None
    assert QualityTierStrategy().select([], policy, effective).selected is None
