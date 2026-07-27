from pydantic import BaseModel, ConfigDict, Field

from domain.enums import (
    LatencyPreference,
    ModelHealthStatus,
    ModelResolutionType,
    ProviderName,
    QualityTier,
)
from domain.money import Money


class ModelCapabilities(BaseModel):
    """Explicit, per-model capability metadata (ADR-002).

    Never assume two models accept identical parameters, token limits, or features —
    every model in the catalogue declares its own capabilities here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_tags: tuple[str, ...] = Field(min_length=1)
    quality_tier: QualityTier
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    supports_tool_use: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = False
    supported_modalities: tuple[str, ...] = ("text",)
    typical_latency: LatencyPreference = Field(
        default=LatencyPreference.BALANCED,
        description=(
            "A coarse, configured classification — never a measured guarantee. Surfaced "
            "via GET /v1/models (Phase 5) so callers can weigh latency without seeing "
            "raw model IDs."
        ),
    )


class ModelPricing(BaseModel):
    """Versioned, configuration-driven pricing (ADR-010).

    Never hardcoded in business logic, and never presented as equal to actual AWS
    billing — see `docs/cost/README.md` (populated in Phase 6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = "USD"
    input_price_per_1k_tokens: Money
    output_price_per_1k_tokens: Money
    pricing_version: int = Field(gt=0)


class ModelHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ModelHealthStatus = ModelHealthStatus.HEALTHY


class ModelResolution(BaseModel):
    """How a model alias maps to a concrete, invocable target.

    `value` holds a direct model ID, a cross-Region/application inference profile
    identifier, or another router alias, depending on `type`. This value is never
    exposed to clients (ADR-006) and is only interpreted by a provider adapter, from
    Phase 3 onward.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ModelResolutionType
    value: str


class ModelDefinition(BaseModel):
    """A single catalogued, routable unit."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    provider: ProviderName
    region: str
    resolution: ModelResolution
    capabilities: ModelCapabilities
    pricing: ModelPricing
    health: ModelHealth = ModelHealth()
