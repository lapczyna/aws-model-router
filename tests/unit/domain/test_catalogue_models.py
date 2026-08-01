from decimal import Decimal

import pytest

from domain.catalogue import ModelCapabilities, ModelDefinition, ModelPricing, ModelResolution
from domain.enums import LatencyPreference, ModelResolutionType, ProviderName, QualityTier

pytestmark = pytest.mark.unit


def _capabilities(**overrides: object) -> ModelCapabilities:
    defaults: dict[str, object] = {
        "capability_tags": ("balanced-text",),
        "quality_tier": QualityTier.STANDARD,
        "max_input_tokens": 1000,
        "max_output_tokens": 500,
    }
    defaults.update(overrides)
    return ModelCapabilities.model_validate(defaults)


def test_typical_latency_defaults_to_balanced() -> None:
    capabilities = _capabilities()
    assert capabilities.typical_latency is LatencyPreference.BALANCED


def test_typical_latency_accepts_explicit_value() -> None:
    capabilities = _capabilities(typical_latency="low")
    assert capabilities.typical_latency is LatencyPreference.LOW


def _model(provider: ProviderName, resolution_type: ModelResolutionType) -> ModelDefinition:
    return ModelDefinition(
        model_alias="test-model",
        provider=provider,
        region="us-east-1",
        resolution=ModelResolution(type=resolution_type, value="some-value"),
        capabilities=_capabilities(),
        pricing=ModelPricing(
            input_price_per_1k_tokens=Decimal("0.001"),
            output_price_per_1k_tokens=Decimal("0.002"),
            pricing_version=1,
        ),
    )


@pytest.mark.parametrize(
    "resolution_type",
    [
        ModelResolutionType.CROSS_REGION_INFERENCE_PROFILE,
        ModelResolutionType.APPLICATION_INFERENCE_PROFILE,
    ],
)
def test_non_bedrock_provider_rejects_bedrock_only_resolution_types(
    resolution_type: ModelResolutionType,
) -> None:
    with pytest.raises(ValueError, match="Bedrock-specific"):
        _model(ProviderName.OPENAI, resolution_type)


@pytest.mark.parametrize(
    "resolution_type",
    [
        ModelResolutionType.CROSS_REGION_INFERENCE_PROFILE,
        ModelResolutionType.APPLICATION_INFERENCE_PROFILE,
        ModelResolutionType.DIRECT_MODEL_ID,
        ModelResolutionType.ROUTER_ALIAS,
    ],
)
def test_bedrock_provider_accepts_every_resolution_type(
    resolution_type: ModelResolutionType,
) -> None:
    model = _model(ProviderName.BEDROCK, resolution_type)
    assert model.resolution.type is resolution_type


def test_non_bedrock_provider_accepts_direct_model_id_and_router_alias() -> None:
    for resolution_type in (ModelResolutionType.DIRECT_MODEL_ID, ModelResolutionType.ROUTER_ALIAS):
        model = _model(ProviderName.OPENAI, resolution_type)
        assert model.resolution.type is resolution_type
