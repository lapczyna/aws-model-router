import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.idempotency import IdempotencyOutcome, IdempotencyReservation
from domain.invocation import InferenceResult
from domain.ports import Clock


@dataclass
class _Record:
    request_hash: str
    in_progress: bool
    result: InferenceResult | None
    expires_at: datetime


class InMemoryIdempotencyStore:
    """Thread-safe, single-process `domain.ports.IdempotencyStore` implementation.

    `stale_reservation_seconds` bounds how long an "in progress" reservation is honored
    if `complete()`/`release()` is never called (e.g. the process crashed mid-request) —
    a safety net independent of any application's `IdempotencyPolicy.retention_seconds`,
    which only governs how long a *completed*, cached result is replayed.
    """

    def __init__(self, clock: Clock, stale_reservation_seconds: float = 300.0) -> None:
        self._clock = clock
        self._stale_reservation_seconds = stale_reservation_seconds
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str], _Record] = {}

    def reserve(
        self, application_id: str, idempotency_key: str, request_hash: str
    ) -> IdempotencyReservation:
        key = (application_id, idempotency_key)
        with self._lock:
            record = self._records.get(key)
            now = self._clock.now()
            if record is not None and now < record.expires_at:
                if record.request_hash != request_hash:
                    return IdempotencyReservation(outcome=IdempotencyOutcome.CONFLICT)
                if record.in_progress:
                    return IdempotencyReservation(outcome=IdempotencyOutcome.IN_PROGRESS)
                return IdempotencyReservation(
                    outcome=IdempotencyOutcome.COMPLETED, cached_result=record.result
                )

            self._records[key] = _Record(
                request_hash=request_hash,
                in_progress=True,
                result=None,
                expires_at=now + timedelta(seconds=self._stale_reservation_seconds),
            )
            return IdempotencyReservation(outcome=IdempotencyOutcome.NEW)

    def complete(
        self,
        application_id: str,
        idempotency_key: str,
        request_hash: str,
        result: InferenceResult,
        *,
        cache_result: bool,
        retention_seconds: int,
    ) -> None:
        key = (application_id, idempotency_key)
        with self._lock:
            if not cache_result:
                # Nothing to replay — release the reservation immediately rather than
                # holding it until a TTL, so a later, genuinely new request isn't
                # blocked (ADR-013: caching, not concurrency dedup, is policy-gated).
                self._records.pop(key, None)
                return
            self._records[key] = _Record(
                request_hash=request_hash,
                in_progress=False,
                result=result,
                expires_at=self._clock.now() + timedelta(seconds=retention_seconds),
            )

    def release(self, application_id: str, idempotency_key: str) -> None:
        with self._lock:
            self._records.pop((application_id, idempotency_key), None)
