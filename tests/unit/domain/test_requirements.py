from decimal import Decimal

import pytest

from domain.enums import LatencyPreference, QualityTier
from domain.requirements import RoutingRequirements, resolve_effective_requirements
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit


def test_effective_requirements_use_policy_defaults_when_client_supplies_nothing() -> None:
    policy = make_policy(
        default_quality_tier=QualityTier.STANDARD,
        maximum_estimated_cost_usd="0.02",
        maximum_output_tokens=500,
    )
    requested = RoutingRequirements(capability="balanced-text")

    effective = resolve_effective_requirements(requested, policy)

    assert effective.quality_tier is QualityTier.STANDARD
    assert effective.maximum_estimated_cost_usd == Decimal("0.02")
    assert effective.maximum_output_tokens == 500
    assert effective.latency_preference is LatencyPreference.BALANCED


def test_client_override_ignored_when_policy_forbids_it() -> None:
    policy = make_policy(
        maximum_estimated_cost_usd="0.02",
        allow_client_overrides={"maximum_estimated_cost_usd": False},
    )
    requested = RoutingRequirements(
        capability="balanced-text", maximum_estimated_cost_usd=Decimal("0.001")
    )

    effective = resolve_effective_requirements(requested, policy)

    assert effective.maximum_estimated_cost_usd == Decimal("0.02")


def test_client_override_can_only_tighten_cost_limit_not_loosen_it() -> None:
    policy = make_policy(
        maximum_estimated_cost_usd="0.02",
        allow_client_overrides={"maximum_estimated_cost_usd": True},
    )
    # Client asks for a *higher* ceiling than the policy allows.
    requested = RoutingRequirements(
        capability="balanced-text", maximum_estimated_cost_usd=Decimal("5.00")
    )

    effective = resolve_effective_requirements(requested, policy)

    assert effective.maximum_estimated_cost_usd == Decimal("0.02")


def test_client_override_can_tighten_cost_limit() -> None:
    policy = make_policy(
        maximum_estimated_cost_usd="0.02",
        allow_client_overrides={"maximum_estimated_cost_usd": True},
    )
    requested = RoutingRequirements(
        capability="balanced-text", maximum_estimated_cost_usd=Decimal("0.001")
    )

    effective = resolve_effective_requirements(requested, policy)

    assert effective.maximum_estimated_cost_usd == Decimal("0.001")


def test_client_quality_tier_override_requires_permission_and_policy_allowance() -> None:
    policy = make_policy(
        allowed_quality_tiers=(QualityTier.STANDARD, QualityTier.PREMIUM),
        default_quality_tier=QualityTier.STANDARD,
        allow_client_overrides={"quality_tier": True},
    )
    requested = RoutingRequirements(capability="balanced-text", quality_tier=QualityTier.PREMIUM)

    effective = resolve_effective_requirements(requested, policy)

    assert effective.quality_tier is QualityTier.PREMIUM


def test_client_quality_tier_override_rejected_if_not_in_allowed_tiers() -> None:
    policy = make_policy(
        allowed_quality_tiers=(QualityTier.STANDARD,),
        default_quality_tier=QualityTier.STANDARD,
        allow_client_overrides={"quality_tier": True},
    )
    # PREMIUM isn't in allowed_quality_tiers even though override permission is granted.
    requested = RoutingRequirements(capability="balanced-text", quality_tier=QualityTier.PREMIUM)

    effective = resolve_effective_requirements(requested, policy)

    assert effective.quality_tier is QualityTier.STANDARD


def test_client_output_token_override_can_only_tighten() -> None:
    policy = make_policy(
        maximum_output_tokens=1000, allow_client_overrides={"maximum_output_tokens": True}
    )
    requested = RoutingRequirements(capability="balanced-text", maximum_output_tokens=5000)

    effective = resolve_effective_requirements(requested, policy)

    assert effective.maximum_output_tokens == 1000


def test_client_latency_preference_override_used_when_permitted() -> None:
    policy = make_policy(allow_client_overrides={"latency_preference": True})
    requested = RoutingRequirements(
        capability="balanced-text", latency_preference=LatencyPreference.LOW
    )

    effective = resolve_effective_requirements(requested, policy)

    assert effective.latency_preference is LatencyPreference.LOW
