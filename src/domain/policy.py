from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.enums import LatencyPreference, QualityTier, RoutingStrategyType
from domain.money import Money


class ClientOverridePermissions(BaseModel):
    """Which client-requested constraints an application's policy allows through.

    Client requirements are requests to satisfy, not authoritative instructions
    (`docs/requirements.md`, FR-2.1) — for each field here, the effective value is the
    client's value only if the corresponding permission is `True`, and even then it can
    only tighten (never loosen) the policy's own limit. See
    `domain.requirements.resolve_effective_requirements`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    quality_tier: bool = False
    maximum_estimated_cost_usd: bool = False
    maximum_output_tokens: bool = False
    latency_preference: bool = False


class RoutingPolicy(BaseModel):
    """The server-side, versioned configuration governing what an application may do."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    policy_version: int = Field(gt=0)
    is_default: bool = False
    allowed_capabilities: tuple[str, ...] = Field(min_length=1)
    allowed_model_aliases: tuple[str, ...] = Field(min_length=1)
    allowed_quality_tiers: tuple[QualityTier, ...] = Field(min_length=1)
    default_quality_tier: QualityTier
    maximum_estimated_cost_usd: Money
    maximum_output_tokens: int = Field(gt=0)
    routing_strategy: RoutingStrategyType
    preferred_model_alias: str | None = None
    latency_preference: LatencyPreference = LatencyPreference.BALANCED
    allow_client_overrides: ClientOverridePermissions = ClientOverridePermissions()

    @model_validator(mode="after")
    def _validate_consistency(self) -> "RoutingPolicy":
        if self.default_quality_tier not in self.allowed_quality_tiers:
            raise ValueError("default_quality_tier must be one of allowed_quality_tiers")

        strategy_needs_preferred_alias = (
            self.routing_strategy is RoutingStrategyType.PREFERRED_MODEL
        )
        if strategy_needs_preferred_alias and not self.preferred_model_alias:
            raise ValueError(
                "preferred_model_alias is required when routing_strategy is preferred_model"
            )

        if (
            self.preferred_model_alias is not None
            and self.preferred_model_alias not in self.allowed_model_aliases
        ):
            raise ValueError("preferred_model_alias must be included in allowed_model_aliases")

        return self
