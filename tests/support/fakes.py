"""Deterministic fakes and model-building helpers shared across unit tests.

Using these instead of the file-backed adapters keeps domain/application unit tests
fast, in-memory, and independent of the filesystem (NFR-5). The file-backed adapters
themselves are tested separately in `tests/unit/adapters/config/`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from domain.catalogue import ModelCapabilities, ModelDefinition, ModelPricing, ModelResolution
from domain.enums import ModelResolutionType, ProviderName, QualityTier
from domain.errors import RoutingPolicyNotFoundError
from domain.experiment import ExperimentPolicy
from domain.fallback import FallbackPolicy
from domain.policy import IdempotencyPolicy, RoutingPolicy


class FixedClock:
    """`domain.ports.Clock` fake returning a fixed, constructor-supplied instant."""

    def __init__(self, fixed_now: datetime) -> None:
        self._fixed_now = fixed_now

    def now(self) -> datetime:
        return self._fixed_now


class SequentialIdentifierGenerator:
    """`domain.ports.IdentifierGenerator` fake producing `<prefix>_1`, `<prefix>_2`, ..."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}_{self._counters[prefix]}"


@dataclass
class InMemoryModelCatalogue:
    """`domain.ports.ModelCatalogue` fake backed by an in-memory list of models."""

    models: Sequence[ModelDefinition]
    version: int = 1

    @property
    def catalogue_version(self) -> int:
        return self.version

    def find_by_capability(self, capability: str) -> Sequence[ModelDefinition]:
        return tuple(m for m in self.models if capability in m.capabilities.capability_tags)

    def get_by_alias(self, model_alias: str) -> ModelDefinition | None:
        for model in self.models:
            if model.model_alias == model_alias:
                return model
        return None


@dataclass
class InMemoryRoutingPolicyRepository:
    """`domain.ports.RoutingPolicyRepository` fake backed by an in-memory mapping."""

    policies_by_application: dict[str, RoutingPolicy] = field(default_factory=dict)
    default_policy: RoutingPolicy | None = None

    def resolve(self, application_id: str) -> RoutingPolicy:
        if application_id in self.policies_by_application:
            return self.policies_by_application[application_id]
        if self.default_policy is not None:
            return self.default_policy
        raise RoutingPolicyNotFoundError(
            f"No routing policy found for application '{application_id}' and no "
            "default policy is configured"
        )


def make_model(
    model_alias: str,
    *,
    capability_tags: tuple[str, ...] = ("balanced-text",),
    quality_tier: QualityTier = QualityTier.STANDARD,
    max_input_tokens: int = 200_000,
    max_output_tokens: int = 4096,
    supports_tool_use: bool = False,
    supports_structured_output: bool = False,
    input_price_per_1k_tokens: str = "0.003",
    output_price_per_1k_tokens: str = "0.015",
) -> ModelDefinition:
    """Build a `ModelDefinition` with sensible defaults, overridable per test."""
    return ModelDefinition(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        region="us-east-1",
        resolution=ModelResolution(
            type=ModelResolutionType.DIRECT_MODEL_ID, value=f"fake.{model_alias}-v1:0"
        ),
        capabilities=ModelCapabilities(
            capability_tags=capability_tags,
            quality_tier=quality_tier,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            supports_tool_use=supports_tool_use,
            supports_structured_output=supports_structured_output,
            supports_streaming=True,
        ),
        pricing=ModelPricing(
            input_price_per_1k_tokens=Decimal(input_price_per_1k_tokens),
            output_price_per_1k_tokens=Decimal(output_price_per_1k_tokens),
            pricing_version=1,
        ),
    )


_UNSET = "__unset__"


def make_policy(
    policy_id: str = "test-policy",
    *,
    policy_version: int = 1,
    is_default: bool = False,
    allowed_capabilities: tuple[str, ...] = ("balanced-text",),
    allowed_model_aliases: tuple[str, ...] = ("balanced-text-primary",),
    allowed_quality_tiers: tuple[QualityTier, ...] = (QualityTier.STANDARD,),
    default_quality_tier: QualityTier = QualityTier.STANDARD,
    maximum_estimated_cost_usd: str = "0.05",
    maximum_output_tokens: int = 1000,
    routing_strategy: str = "preferred_model",
    preferred_model_alias: str | None = _UNSET,
    allow_client_overrides: dict[str, bool] | None = None,
    fallback_policy: FallbackPolicy | None = None,
    experiment_policy: ExperimentPolicy | None = None,
    idempotency_policy: IdempotencyPolicy | None = None,
) -> RoutingPolicy:
    """Build a `RoutingPolicy` with sensible defaults, overridable per test.

    `preferred_model_alias` defaults to the first entry of `allowed_model_aliases` when
    `routing_strategy` is `preferred_model` and the caller didn't override it explicitly
    (e.g. to `None`) — so overriding just `allowed_model_aliases` never breaks the
    "preferred alias must be allowed" invariant enforced by `RoutingPolicy`.
    """
    if preferred_model_alias is _UNSET:
        preferred_model_alias = (
            allowed_model_aliases[0] if routing_strategy == "preferred_model" else None
        )
    return RoutingPolicy.model_validate(
        {
            "policy_id": policy_id,
            "policy_version": policy_version,
            "is_default": is_default,
            "allowed_capabilities": allowed_capabilities,
            "allowed_model_aliases": allowed_model_aliases,
            "allowed_quality_tiers": allowed_quality_tiers,
            "default_quality_tier": default_quality_tier,
            "maximum_estimated_cost_usd": maximum_estimated_cost_usd,
            "maximum_output_tokens": maximum_output_tokens,
            "routing_strategy": routing_strategy,
            "preferred_model_alias": preferred_model_alias,
            "allow_client_overrides": allow_client_overrides or {},
            "fallback_policy": fallback_policy or FallbackPolicy(),
            "experiment_policy": experiment_policy,
            "idempotency_policy": idempotency_policy or IdempotencyPolicy(),
        }
    )
