from typing import Any

import pytest
from pydantic import ValidationError

from domain.enums import QualityTier, RoutingStrategyType
from domain.policy import RoutingPolicy

pytestmark = pytest.mark.unit


def _base_policy_kwargs() -> dict[str, Any]:
    return {
        "policy_id": "test-policy",
        "policy_version": 1,
        "allowed_capabilities": ["balanced-text"],
        "allowed_model_aliases": ["balanced-text-primary"],
        "allowed_quality_tiers": ["standard"],
        "default_quality_tier": "standard",
        "maximum_estimated_cost_usd": "0.05",
        "maximum_output_tokens": 1000,
        "routing_strategy": "preferred_model",
        "preferred_model_alias": "balanced-text-primary",
    }


def test_valid_policy_parses() -> None:
    policy = RoutingPolicy.model_validate(_base_policy_kwargs())
    assert policy.policy_id == "test-policy"
    assert policy.routing_strategy is RoutingStrategyType.PREFERRED_MODEL
    assert policy.default_quality_tier is QualityTier.STANDARD


def test_preferred_model_alias_required_for_preferred_model_strategy() -> None:
    kwargs = _base_policy_kwargs()
    kwargs["preferred_model_alias"] = None
    with pytest.raises(ValidationError, match="preferred_model_alias is required"):
        RoutingPolicy.model_validate(kwargs)


def test_preferred_model_alias_must_be_in_allowed_model_aliases() -> None:
    kwargs = _base_policy_kwargs()
    kwargs["preferred_model_alias"] = "some-other-model"
    with pytest.raises(ValidationError, match="must be included in allowed_model_aliases"):
        RoutingPolicy.model_validate(kwargs)


def test_default_quality_tier_must_be_in_allowed_quality_tiers() -> None:
    kwargs = _base_policy_kwargs()
    kwargs["allowed_quality_tiers"] = ["premium"]
    with pytest.raises(ValidationError, match="default_quality_tier must be one of"):
        RoutingPolicy.model_validate(kwargs)


def test_lowest_cost_strategy_does_not_require_preferred_model_alias() -> None:
    kwargs = _base_policy_kwargs()
    kwargs["routing_strategy"] = "lowest_cost"
    kwargs["preferred_model_alias"] = None
    policy = RoutingPolicy.model_validate(kwargs)
    assert policy.preferred_model_alias is None


def test_rejects_unknown_fields() -> None:
    kwargs = _base_policy_kwargs()
    kwargs["unexpected_field"] = "nope"
    with pytest.raises(ValidationError):
        RoutingPolicy.model_validate(kwargs)
