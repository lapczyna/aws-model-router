import pytest

from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository
from domain.enums import ModelHealthStatus
from domain.invocation import InvocationAttemptStatus

pytestmark = pytest.mark.unit


def test_unknown_model_is_healthy_by_default() -> None:
    repository = InMemoryModelHealthRepository()
    assert repository.get_health("never-seen") is ModelHealthStatus.HEALTHY


def test_success_keeps_model_healthy() -> None:
    repository = InMemoryModelHealthRepository()
    repository.record_outcome("model-a", InvocationAttemptStatus.SUCCEEDED)
    assert repository.get_health("model-a") is ModelHealthStatus.HEALTHY


def test_consecutive_failures_below_threshold_stay_healthy() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=3, unavailable_after=5)
    for _ in range(2):
        repository.record_outcome("model-a", InvocationAttemptStatus.THROTTLED)
    assert repository.get_health("model-a") is ModelHealthStatus.HEALTHY


def test_consecutive_failures_at_degraded_threshold_are_degraded() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=3, unavailable_after=5)
    for _ in range(3):
        repository.record_outcome("model-a", InvocationAttemptStatus.THROTTLED)
    assert repository.get_health("model-a") is ModelHealthStatus.DEGRADED


def test_consecutive_failures_at_unavailable_threshold_are_unavailable() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=3, unavailable_after=5)
    for _ in range(5):
        repository.record_outcome("model-a", InvocationAttemptStatus.TRANSIENT_ERROR)
    assert repository.get_health("model-a") is ModelHealthStatus.UNAVAILABLE


def test_success_resets_failure_count() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=3, unavailable_after=5)
    for _ in range(4):
        repository.record_outcome("model-a", InvocationAttemptStatus.TIMEOUT)
    repository.record_outcome("model-a", InvocationAttemptStatus.SUCCEEDED)
    assert repository.get_health("model-a") is ModelHealthStatus.HEALTHY

    for _ in range(2):
        repository.record_outcome("model-a", InvocationAttemptStatus.TIMEOUT)
    assert repository.get_health("model-a") is ModelHealthStatus.HEALTHY  # still below 3


def test_non_retryable_error_does_not_affect_health() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=1, unavailable_after=2)
    for _ in range(10):
        repository.record_outcome("model-a", InvocationAttemptStatus.NON_RETRYABLE_ERROR)
    assert repository.get_health("model-a") is ModelHealthStatus.HEALTHY


def test_models_are_tracked_independently() -> None:
    repository = InMemoryModelHealthRepository(degraded_after=1, unavailable_after=2)
    repository.record_outcome("model-a", InvocationAttemptStatus.THROTTLED)
    repository.record_outcome("model-a", InvocationAttemptStatus.THROTTLED)
    assert repository.get_health("model-a") is ModelHealthStatus.UNAVAILABLE
    assert repository.get_health("model-b") is ModelHealthStatus.HEALTHY


@pytest.mark.parametrize(
    ("degraded_after", "unavailable_after"),
    [(0, 5), (3, 3), (5, 3)],
)
def test_invalid_thresholds_raise(degraded_after: int, unavailable_after: int) -> None:
    with pytest.raises(ValueError, match="degraded_after"):
        InMemoryModelHealthRepository(
            degraded_after=degraded_after, unavailable_after=unavailable_after
        )
