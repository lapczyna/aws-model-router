import pytest

from adapters.bedrock.retry import RetryPolicy, compute_backoff_delay

pytestmark = pytest.mark.unit


def test_backoff_delay_scales_with_jitter_fraction() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=100.0)

    assert compute_backoff_delay(1, policy, jitter_fraction=0.0) == 0.0
    assert compute_backoff_delay(1, policy, jitter_fraction=1.0) == 1.0
    assert compute_backoff_delay(1, policy, jitter_fraction=0.5) == 0.5


def test_backoff_delay_grows_exponentially_with_attempt() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=100.0)

    assert compute_backoff_delay(1, policy, jitter_fraction=1.0) == 1.0
    assert compute_backoff_delay(2, policy, jitter_fraction=1.0) == 2.0
    assert compute_backoff_delay(3, policy, jitter_fraction=1.0) == 4.0
    assert compute_backoff_delay(4, policy, jitter_fraction=1.0) == 8.0


def test_backoff_delay_is_capped_at_max_delay() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=3.0)

    assert compute_backoff_delay(10, policy, jitter_fraction=1.0) == 3.0


def test_default_retry_policy_values() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.base_delay_seconds == 0.5
    assert policy.max_delay_seconds == 8.0
