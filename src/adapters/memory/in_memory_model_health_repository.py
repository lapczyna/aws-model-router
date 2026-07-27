import threading

from domain.enums import ModelHealthStatus
from domain.invocation import InvocationAttemptStatus

_HEALTH_AFFECTING_STATUSES = frozenset(
    {
        InvocationAttemptStatus.THROTTLED,
        InvocationAttemptStatus.TRANSIENT_ERROR,
        InvocationAttemptStatus.TIMEOUT,
    }
)


class InMemoryModelHealthRepository:
    """Thread-safe, single-process `domain.ports.ModelHealthRepository` implementation
    (ADR-020): health is derived purely from a per-model consecutive-failure counter —
    any `SUCCEEDED` outcome resets it to zero, and only throttled/transient/timeout
    failures increment it. `NON_RETRYABLE_ERROR` never affects health — a permanent
    failure reflects the specific request (e.g. an unsupported parameter), not the
    model's operational state.

    Scope limitation (ADR-020): this tracks health only within one Lambda execution
    environment's lifetime, not fleet-wide across every concurrent execution
    environment — a deliberate, documented trade-off, not an oversight.
    """

    def __init__(self, degraded_after: int = 3, unavailable_after: int = 5) -> None:
        if degraded_after < 1 or unavailable_after <= degraded_after:
            raise ValueError("require 1 <= degraded_after < unavailable_after")
        self._degraded_after = degraded_after
        self._unavailable_after = unavailable_after
        self._lock = threading.Lock()
        self._consecutive_failures: dict[str, int] = {}

    def get_health(self, model_alias: str) -> ModelHealthStatus:
        with self._lock:
            failures = self._consecutive_failures.get(model_alias, 0)
        if failures >= self._unavailable_after:
            return ModelHealthStatus.UNAVAILABLE
        if failures >= self._degraded_after:
            return ModelHealthStatus.DEGRADED
        return ModelHealthStatus.HEALTHY

    def record_outcome(self, model_alias: str, status: InvocationAttemptStatus) -> None:
        with self._lock:
            if status is InvocationAttemptStatus.SUCCEEDED:
                self._consecutive_failures[model_alias] = 0
            elif status in _HEALTH_AFFECTING_STATUSES:
                self._consecutive_failures[model_alias] = (
                    self._consecutive_failures.get(model_alias, 0) + 1
                )
