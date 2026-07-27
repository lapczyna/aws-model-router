import pytest

from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ModelHealthStatus, QualityTier, Role
from domain.filtering import build_route_candidates, evaluate_candidate
from domain.messages import Message
from domain.reason_codes import RoutingReasonCode
from domain.requirements import RoutingRequirements, resolve_effective_requirements
from tests.support.fakes import make_model, make_policy

pytestmark = pytest.mark.unit

TOKEN_ESTIMATOR = DefaultTokenEstimator()
COST_ESTIMATOR = DefaultCostEstimator()
MESSAGES = (Message(role=Role.USER, content="hello there"),)


def _evaluate(model, policy, health_status=ModelHealthStatus.HEALTHY, **requirement_overrides):
    requested = RoutingRequirements(capability="balanced-text", **requirement_overrides)
    effective = resolve_effective_requirements(requested, policy)
    return evaluate_candidate(
        model, effective, policy, TOKEN_ESTIMATOR, COST_ESTIMATOR, MESSAGES, health_status
    )


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


def test_unavailable_health_excludes_candidate() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy, health_status=ModelHealthStatus.UNAVAILABLE)

    assert candidate.eligible is False
    assert RoutingReasonCode.MODEL_UNHEALTHY in candidate.reason_codes


def test_degraded_health_stays_eligible_but_is_flagged() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy, health_status=ModelHealthStatus.DEGRADED)

    assert candidate.eligible is True
    assert RoutingReasonCode.MODEL_DEGRADED in candidate.reason_codes


def test_healthy_status_adds_no_health_reason_code() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))

    candidate = _evaluate(model, policy, health_status=ModelHealthStatus.HEALTHY)

    assert RoutingReasonCode.MODEL_UNHEALTHY not in candidate.reason_codes
    assert RoutingReasonCode.MODEL_DEGRADED not in candidate.reason_codes


class _FixedHealthRepository:
    def __init__(self, health_by_alias: dict[str, ModelHealthStatus]) -> None:
        self._health_by_alias = health_by_alias

    def get_health(self, model_alias: str) -> ModelHealthStatus:
        return self._health_by_alias.get(model_alias, ModelHealthStatus.HEALTHY)

    def record_outcome(self, model_alias: str, status: object) -> None:
        raise AssertionError("not used by build_route_candidates")


def test_build_route_candidates_consults_health_repository_per_model() -> None:
    healthy_model = make_model("healthy-model", capability_tags=("balanced-text",))
    unavailable_model = make_model("unavailable-model", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("healthy-model", "unavailable-model"))
    requested = RoutingRequirements(capability="balanced-text")
    effective = resolve_effective_requirements(requested, policy)
    health_repository = _FixedHealthRepository({"unavailable-model": ModelHealthStatus.UNAVAILABLE})

    candidates = build_route_candidates(
        [healthy_model, unavailable_model],
        effective,
        policy,
        TOKEN_ESTIMATOR,
        COST_ESTIMATOR,
        MESSAGES,
        health_repository,
    )

    by_alias = {candidate.model_alias: candidate for candidate in candidates}
    assert by_alias["healthy-model"].eligible is True
    assert by_alias["unavailable-model"].eligible is False
    assert RoutingReasonCode.MODEL_UNHEALTHY in by_alias["unavailable-model"].reason_codes


def test_build_route_candidates_defaults_to_healthy_without_repository() -> None:
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("balanced-text-primary",))
    requested = RoutingRequirements(capability="balanced-text")
    effective = resolve_effective_requirements(requested, policy)

    candidates = build_route_candidates(
        [model], effective, policy, TOKEN_ESTIMATOR, COST_ESTIMATOR, MESSAGES
    )

    assert candidates[0].eligible is True
