from datetime import UTC, datetime

import pytest

from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ModelHealthStatus, QualityTier, Role
from domain.errors import ConfigurationError, RoutingPolicyNotFoundError
from domain.messages import Message
from domain.reason_codes import RoutingReasonCode
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements
from tests.support.fakes import (
    FixedClock,
    InMemoryModelCatalogue,
    InMemoryRoutingPolicyRepository,
    SequentialIdentifierGenerator,
    make_model,
    make_policy,
)

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _service(catalogue, policy_repository, model_health_repository=None) -> RouteEvaluationService:
    return RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=FixedClock(FIXED_NOW),
        identifier_generator=SequentialIdentifierGenerator(),
        model_health_repository=model_health_repository,
    )


def _request(application_id: str = "app-1", **requirement_overrides) -> InferenceRequest:
    requirements = RoutingRequirements(capability="balanced-text", **requirement_overrides)
    return InferenceRequest(
        application_id=application_id,
        messages=(Message(role=Role.USER, content="Summarize this incident report."),),
        requirements=requirements,
    )


def test_preferred_model_selected() -> None:
    preferred = make_model("preferred", capability_tags=("balanced-text",))
    other = make_model("other", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("preferred", "other"),
        routing_strategy="preferred_model",
        preferred_model_alias="preferred",
        maximum_estimated_cost_usd="10",
    )
    service = _service(
        InMemoryModelCatalogue([preferred, other]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias == "preferred"
    assert RoutingReasonCode.CAPABILITY_MATCH in decision.reason_codes


def test_disallowed_model_excluded_even_if_otherwise_eligible() -> None:
    allowed = make_model("allowed-model", capability_tags=("balanced-text",))
    disallowed = make_model(
        "disallowed-model",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.0001",
        output_price_per_1k_tokens="0.0001",
    )
    policy = make_policy(
        allowed_model_aliases=("allowed-model",),
        routing_strategy="lowest_cost",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="10",
    )
    service = _service(
        InMemoryModelCatalogue([allowed, disallowed]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias == "allowed-model"
    disallowed_candidate = next(
        c for c in decision.considered_candidates if c.model_alias == "disallowed-model"
    )
    assert disallowed_candidate.eligible is False
    assert RoutingReasonCode.MODEL_NOT_ALLOWED in disallowed_candidate.reason_codes


def test_missing_capability_in_catalogue_yields_required_capability_unavailable() -> None:
    model = make_model("model-a", capability_tags=("economical-text",))
    policy = make_policy(
        allowed_capabilities=("balanced-text", "economical-text"),
        allowed_model_aliases=("model-a",),
        preferred_model_alias=None,
        routing_strategy="lowest_cost",
    )
    service = _service(
        InMemoryModelCatalogue([model]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request())  # requests "balanced-text"; catalogue has none

    assert decision.selected_model_alias is None
    assert decision.reason_codes == (RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE,)
    assert decision.considered_candidates == ()


def test_capability_not_permitted_by_policy_yields_required_capability_unavailable() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_capabilities=("economical-text",), allowed_model_aliases=("model-a",)
    )
    service = _service(
        InMemoryModelCatalogue([model]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request())  # requests "balanced-text"; policy doesn't allow it

    assert decision.selected_model_alias is None
    assert decision.reason_codes == (RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE,)


def test_token_limit_exceeded_yields_no_eligible_model() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",), max_output_tokens=10)
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        maximum_output_tokens=1000,
    )
    service = _service(
        InMemoryModelCatalogue([model]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request(maximum_output_tokens=500))

    assert decision.selected_model_alias is None
    assert decision.reason_codes == (RoutingReasonCode.NO_ELIGIBLE_MODEL,)
    candidate = decision.considered_candidates[0]
    assert RoutingReasonCode.TOKEN_LIMIT_EXCEEDED in candidate.reason_codes


def test_request_cost_exceeded_yields_no_eligible_model() -> None:
    model = make_model(
        "model-a",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="10",
        output_price_per_1k_tokens="10",
    )
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        maximum_estimated_cost_usd="0.001",
    )
    service = _service(
        InMemoryModelCatalogue([model]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias is None
    assert decision.reason_codes == (RoutingReasonCode.NO_ELIGIBLE_MODEL,)
    candidate = decision.considered_candidates[0]
    assert RoutingReasonCode.COST_LIMIT_EXCEEDED in candidate.reason_codes


def test_lowest_cost_eligible_model_selected() -> None:
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
    service = _service(
        InMemoryModelCatalogue([expensive, cheap]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias == "cheap"
    assert RoutingReasonCode.LOWEST_ESTIMATED_COST in decision.reason_codes


def test_quality_tier_applied() -> None:
    standard = make_model(
        "standard-model", capability_tags=("balanced-text",), quality_tier=QualityTier.STANDARD
    )
    premium = make_model(
        "premium-model",
        capability_tags=("balanced-text",),
        quality_tier=QualityTier.PREMIUM,
        input_price_per_1k_tokens="0.0001",
        output_price_per_1k_tokens="0.0001",
    )
    policy = make_policy(
        allowed_model_aliases=("standard-model", "premium-model"),
        allowed_quality_tiers=(QualityTier.STANDARD, QualityTier.PREMIUM),
        default_quality_tier=QualityTier.STANDARD,
        routing_strategy="quality_tier",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="100",
    )
    service = _service(
        InMemoryModelCatalogue([standard, premium]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
    )

    # premium-model is cheaper, but the effective (default) quality tier is "standard",
    # so quality_tier strategy must select standard-model despite the cost difference.
    decision = service.evaluate(_request())

    assert decision.selected_model_alias == "standard-model"
    assert RoutingReasonCode.QUALITY_TIER_MATCH in decision.reason_codes


def test_no_eligible_route_when_every_candidate_is_excluded() -> None:
    model = make_model(
        "model-a",
        capability_tags=("balanced-text",),
        quality_tier=QualityTier.PREMIUM,  # mismatches policy's standard-only tier
    )
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        allowed_quality_tiers=(QualityTier.STANDARD,),
        default_quality_tier=QualityTier.STANDARD,
        preferred_model_alias="model-a",
    )
    service = _service(
        InMemoryModelCatalogue([model]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias is None
    assert decision.reason_codes == (RoutingReasonCode.NO_ELIGIBLE_MODEL,)


def test_missing_policy_raises_when_no_default_configured() -> None:
    service = _service(InMemoryModelCatalogue([]), InMemoryRoutingPolicyRepository())

    with pytest.raises(RoutingPolicyNotFoundError):
        service.evaluate(_request(application_id="totally-unknown"))


def test_application_specific_policy_is_used_over_default() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    app_policy = make_policy(
        policy_id="app-specific",
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
    )
    default_policy = make_policy(policy_id="default-policy", is_default=True)
    service = _service(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(
            policies_by_application={"app-1": app_policy}, default_policy=default_policy
        ),
    )

    decision = service.evaluate(_request(application_id="app-1"))

    assert decision.policy_id == "app-specific"


def test_default_policy_used_when_no_application_specific_policy_exists() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    default_policy = make_policy(
        policy_id="default-policy",
        is_default=True,
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
    )
    service = _service(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=default_policy),
    )

    decision = service.evaluate(_request(application_id="some-other-app"))

    assert decision.policy_id == "default-policy"
    assert decision.selected_model_alias == "model-a"


def test_service_propagates_configuration_error_from_repository() -> None:
    class _BrokenRepository:
        def resolve(self, application_id: str):
            raise ConfigurationError("boom")

    service = _service(InMemoryModelCatalogue([]), _BrokenRepository())

    with pytest.raises(ConfigurationError):
        service.evaluate(_request())


def test_reason_codes_are_returned_in_stable_canonical_order() -> None:
    cheap = make_model(
        "cheap",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    policy = make_policy(
        allowed_model_aliases=("cheap",),
        routing_strategy="lowest_cost",
        preferred_model_alias=None,
        maximum_estimated_cost_usd="100",
    )
    service = _service(
        InMemoryModelCatalogue([cheap]), InMemoryRoutingPolicyRepository(default_policy=policy)
    )

    decision = service.evaluate(_request())

    canonical_index = {code: i for i, code in enumerate(RoutingReasonCode)}
    assert list(decision.reason_codes) == sorted(
        decision.reason_codes, key=lambda code: canonical_index[code]
    )


class _FixedHealthRepository:
    def __init__(self, health_by_alias: dict[str, ModelHealthStatus]) -> None:
        self._health_by_alias = health_by_alias

    def get_health(self, model_alias: str) -> ModelHealthStatus:
        return self._health_by_alias.get(model_alias, ModelHealthStatus.HEALTHY)

    def record_outcome(self, model_alias: str, status: object) -> None:
        raise AssertionError("not used by RouteEvaluationService.evaluate")


def test_unavailable_model_health_excludes_it_from_selection() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    service = _service(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        model_health_repository=_FixedHealthRepository({"model-a": ModelHealthStatus.UNAVAILABLE}),
    )

    decision = service.evaluate(_request())

    assert decision.selected_model_alias is None
    assert RoutingReasonCode.MODEL_UNHEALTHY in decision.considered_candidates[0].reason_codes


def test_repeated_evaluation_is_deterministic() -> None:
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
    service = _service(
        InMemoryModelCatalogue([expensive, cheap]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
    )

    first = service.evaluate(_request())
    second = service.evaluate(_request())

    assert first.selected_model_alias == second.selected_model_alias
    assert first.reason_codes == second.reason_codes
    assert first.estimated_cost == second.estimated_cost
    # decision_id and created_at are expected to differ (or be regenerated) per call —
    # determinism is about the routing outcome, not about identity/timestamp fields.
