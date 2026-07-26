"""Bounded retry policy with full-jitter exponential backoff.

"Full jitter" (AWS's recommended algorithm): the delay before a retry is a random value
between 0 and the exponentially-growing, capped delay — this spreads out retries from
concurrent callers instead of having them all retry in lockstep. `jitter_fraction` is
injected (rather than sampled internally) so tests can assert exact, deterministic
delay values.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0


def compute_backoff_delay(attempt: int, policy: RetryPolicy, jitter_fraction: float) -> float:
    """Delay before retrying `attempt` (1-indexed: the attempt that just failed).

    `jitter_fraction` must be in `[0, 1)`.
    """
    capped_delay: float = min(
        policy.max_delay_seconds, policy.base_delay_seconds * (2 ** (attempt - 1))
    )
    return capped_delay * jitter_fraction
