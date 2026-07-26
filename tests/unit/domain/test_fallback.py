import pytest
from pydantic import ValidationError

from domain.fallback import FallbackPolicy

pytestmark = pytest.mark.unit


def test_defaults_mean_no_fallback() -> None:
    policy = FallbackPolicy()
    assert policy.fallback_model_aliases == ()
    assert policy.maximum_attempts == 1


def test_accepts_configured_chain() -> None:
    policy = FallbackPolicy(fallback_model_aliases=("model-b", "model-c"), maximum_attempts=3)
    assert policy.fallback_model_aliases == ("model-b", "model-c")
    assert policy.maximum_attempts == 3


def test_rejects_maximum_attempts_below_one() -> None:
    with pytest.raises(ValidationError):
        FallbackPolicy(maximum_attempts=0)


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FallbackPolicy.model_validate({"fallback_model_aliases": [], "unexpected": True})
