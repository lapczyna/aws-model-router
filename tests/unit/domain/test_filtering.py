import pytest

from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import QualityTier, Role
from domain.filtering import evaluate_candidate
from domain.messages import Message
from domain.reason_codes import RoutingReasonCode
from domain.requirements import RoutingRequirements, resolve_effective_requirements
from tests.support.fakes import make_model, make_policy

pytestmark = pytest.mark.unit

TOKEN_ESTIMATOR = DefaultTokenEstimator()
COST_ESTIMATOR = DefaultCostEstimator()
MESSAGES = (Message(role=Role.USER, content="hello there"),)


def _evaluate(model, policy, **requirement_overrides):
    requested = RoutingRequirements(capability="balanced-text", **requirement_overrides)
    effective = resolve_effective_requirements(requested, policy)
    return evaluate_candidate(model, effective, policy, TOKEN_ESTIMATOR, COST_ESTIMATOR, MESSAGES)


def test_capability_match_included_for_matching_model() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy)

    assert candidate.eligible is True
    assert RoutingReasonCode.CAPABILITY_MATCH in candidate.reason_codes


def test_capability_mismatch_excludes_candidate_without_negative_code() -> None:
    model = make_model("economical-text-primary", capability_tags=("economical-text",))
    policy = make_policy(
        allowed_capabilities=("balanced-text", "economical-text"),
        allowed_model_aliases=("economical-text-primary",),
    )

    candidate = _evaluate(model, policy)

    assert candidate.eligible is False
    assert RoutingReasonCode.CAPABILITY_MATCH not in candidate.reason_codes


def test_disallowed_model_excluded() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("some-other-model",))

    candidate = _evaluate(model, policy)

    assert candidate.eligible is False
    assert RoutingReasonCode.MODEL_NOT_ALLOWED in candidate.reason_codes
    assert RoutingReasonCode.MODEL_ALLOWED not in candidate.reason_codes


def test_token_limit_exceeded_excludes_candidate() -> None:
    model = make_model(
        "balanced-text-primary", capability_tags=("balanced-text",), max_output_tokens=10
    )
    policy = make_policy(
        allowed_model_aliases=("balanced-text-primary",), maximum_output_tokens=1000
    )

    candidate = _evaluate(model, policy, maximum_output_tokens=500)

    assert candidate.eligible is False
    assert RoutingReasonCode.TOKEN_LIMIT_EXCEEDED in candidate.reason_codes


def test_cost_limit_exceeded_excludes_candidate() -> None:
    model = make_model(
        "balanced-text-primary",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="10.00",
        output_price_per_1k_tokens="10.00",
    )
    policy = make_policy(
        allowed_model_aliases=("balanced-text-primary",), maximum_estimated_cost_usd="0.001"
    )

    candidate = _evaluate(model, policy)

    assert candidate.eligible is False
    assert RoutingReasonCode.COST_LIMIT_EXCEEDED in candidate.reason_codes
    assert RoutingReasonCode.WITHIN_COST_LIMIT not in candidate.reason_codes


def test_within_cost_limit_marks_candidate_eligible() -> None:
    model = make_model(
        "balanced-text-primary",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    policy = make_policy(
        allowed_model_aliases=("balanced-text-primary",), maximum_estimated_cost_usd="5.00"
    )

    candidate = _evaluate(model, policy)

    assert candidate.eligible is True
    assert RoutingReasonCode.WITHIN_COST_LIMIT in candidate.reason_codes


def test_quality_tier_mismatch_excludes_candidate() -> None:
    model = make_model(
        "balanced-text-primary",
        capability_tags=("balanced-text",),
        quality_tier=QualityTier.PREMIUM,
    )
    policy = make_policy(
        allowed_model_aliases=("balanced-text-primary",),
        allowed_quality_tiers=(QualityTier.STANDARD, QualityTier.PREMIUM),
        default_quality_tier=QualityTier.STANDARD,
    )

    candidate = _evaluate(model, policy)

    assert candidate.eligible is False
    assert RoutingReasonCode.QUALITY_TIER_MATCH not in candidate.reason_codes


def test_requires_tool_use_excludes_model_without_support() -> None:
    model = make_model(
        "balanced-text-primary", capability_tags=("balanced-text",), supports_tool_use=False
    )
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy, requires_tool_use=True)

    assert candidate.eligible is False
    assert RoutingReasonCode.CAPABILITY_MATCH not in candidate.reason_codes


def test_requires_tool_use_allows_model_with_support() -> None:
    model = make_model(
        "balanced-text-primary", capability_tags=("balanced-text",), supports_tool_use=True
    )
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy, requires_tool_use=True)

    assert candidate.eligible is True
    assert RoutingReasonCode.CAPABILITY_MATCH in candidate.reason_codes


def test_reason_codes_are_in_canonical_order() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy)

    assert list(candidate.reason_codes) == sorted(
        candidate.reason_codes, key=lambda code: list(RoutingReasonCode).index(code)
    )
