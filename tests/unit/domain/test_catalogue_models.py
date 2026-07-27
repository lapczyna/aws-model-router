import pytest

from domain.catalogue import ModelCapabilities
from domain.enums import LatencyPreference, QualityTier

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
