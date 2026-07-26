import threading
from datetime import UTC, datetime, timedelta

import pytest

from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from domain.decision import RoutingDecision
from domain.enums import ProviderName, Role, StopReason
from domain.idempotency import IdempotencyOutcome
from domain.invocation import InferenceResult
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import Usage
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _MutableClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _result() -> InferenceResult:
    decision = RoutingDecision(
        decision_id="dec_1",
        application_id="app-1",
        created_at=FIXED_NOW,
        policy_id=make_policy().policy_id,
        policy_version=1,
        capability="balanced-text",
        selected_model_alias="model-a",
        provider=ProviderName.BEDROCK,
        reason_codes=(RoutingReasonCode.CAPABILITY_MATCH,),
        considered_candidates=(),
    )
    response = ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hi"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    return InferenceResult(decision=decision, response=response, invocation_attempts=())


def test_reserve_on_fresh_key_returns_new() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    reservation = store.reserve("app-1", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.NEW


def test_reserve_while_in_progress_returns_in_progress() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-1", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.IN_PROGRESS


def test_reserve_with_different_hash_while_in_progress_returns_conflict() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-1", "key-1", "hash-2")
    assert reservation.outcome is IdempotencyOutcome.CONFLICT


def test_complete_with_caching_makes_result_replayable() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    result = _result()
    store.complete("app-1", "key-1", "hash-1", result, cache_result=True, retention_seconds=300)

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.COMPLETED
    assert reservation.cached_result == result


def test_complete_without_caching_releases_the_key() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    store.complete("app-1", "key-1", "hash-1", _result(), cache_result=False, retention_seconds=300)

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_release_frees_the_key() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    store.release("app-1", "key-1")

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_cached_result_expires_after_retention_seconds() -> None:
    clock = _MutableClock(FIXED_NOW)
    store = InMemoryIdempotencyStore(clock=clock)
    store.reserve("app-1", "key-1", "hash-1")
    store.complete("app-1", "key-1", "hash-1", _result(), cache_result=True, retention_seconds=10)

    clock.advance(11)
    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_stale_in_progress_reservation_expires_as_a_crash_recovery_safety_net() -> None:
    clock = _MutableClock(FIXED_NOW)
    store = InMemoryIdempotencyStore(clock=clock, stale_reservation_seconds=5)
    store.reserve("app-1", "key-1", "hash-1")
    # Simulate the process crashing before complete()/release() is ever called.

    clock.advance(6)
    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_different_applications_do_not_share_keys() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-2", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.NEW


def test_concurrent_reserve_calls_only_let_one_thread_through() -> None:
    store = InMemoryIdempotencyStore(clock=_MutableClock(FIXED_NOW))
    outcomes: list[IdempotencyOutcome] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        reservation = store.reserve("app-1", "key-1", "hash-1")
        with lock:
            outcomes.append(reservation.outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert outcomes.count(IdempotencyOutcome.NEW) == 1
    assert outcomes.count(IdempotencyOutcome.IN_PROGRESS) == 7
