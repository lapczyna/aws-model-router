"""Load and fault-injection tests (Phase 9): higher-concurrency and randomized-failure
extensions of the deterministic fallback/idempotency tests in
`test_invocation_orchestrator.py`. Still fully in-process, no real AWS calls — see
`docs/security/resilience-test-plan.md` for exactly what this proves versus what still
requires a real deployed stack to validate (real Lambda cold starts, real API Gateway
throttling, real DynamoDB capacity behavior).

`Uuid4IdentifierGenerator` (not `SequentialIdentifierGenerator`) is used throughout:
the sequential fake's `dict.get(...) + 1` counter update is not atomic across threads,
which would risk duplicate decision IDs under genuine concurrency — a fake-specific
limitation, not a real orchestrator bug, but exactly the kind of thing a load test must
not accidentally introduce as a false failure.
"""

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import IdempotencyInProgressError, ProviderError
from domain.fallback import FallbackPolicy
from domain.invocation import InvocationAttemptStatus
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements
from domain.usage import Usage
from shared.identifiers import Uuid4IdentifierGenerator
from tests.support.fakes import (
    FixedClock,
    InMemoryModelCatalogue,
    InMemoryRoutingPolicyRepository,
    make_model,
    make_policy,
)

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _MutableClock:
    def __init__(self, start: datetime) -> None:
        self._now = start
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


def _response(model_alias: str) -> ProviderResponse:
    return ProviderResponse(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="ok"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=5, output_tokens=5),
    )


def _request(
    idempotency_key: str | None = None, conversation_id: str | None = None
) -> InferenceRequest:
    return InferenceRequest(
        application_id="app-1",
        messages=(Message(role=Role.USER, content="hello"),),
        requirements=RoutingRequirements(capability="balanced-text"),
        idempotency_key=idempotency_key,
        conversation_id=conversation_id,
    )


class RandomFaultModelProvider:
    """Thread-safe fake provider: fails a configurable fraction of calls to specific
    model aliases with a randomly-chosen retryable category, otherwise succeeds.
    Uses its own seeded `random.Random` for reproducibility — this is a controlled
    simulation, not genuine nondeterminism.
    """

    def __init__(self, failure_rate: dict[str, float], seed: int = 0) -> None:
        self._failure_rate = failure_rate
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        with self._lock:
            self.calls.append(request.model_alias)
            roll = self._rng.random()
            category = self._rng.choice(
                [ProviderErrorCategory.THROTTLED, ProviderErrorCategory.TRANSIENT]
            )
        rate = self._failure_rate.get(request.model_alias, 0.0)
        if roll < rate:
            raise ProviderError("injected failure", category=category)
        return _response(request.model_alias)


class AlwaysFailModelProvider:
    """Fails every call to `failing_alias`; succeeds for anything else."""

    def __init__(self, failing_alias: str) -> None:
        self._failing_alias = failing_alias

    def invoke(self, request: Any) -> ProviderResponse:
        if request.model_alias == self._failing_alias:
            raise ProviderError("injected failure", category=ProviderErrorCategory.THROTTLED)
        return _response(request.model_alias)


class BlockingModelProvider:
    """Blocks every call until `release_event` is set — used to force many concurrent
    requests to genuinely overlap in time, not just interleave quickly."""

    def __init__(self, release_event: threading.Event) -> None:
        self._release_event = release_event
        self._lock = threading.Lock()
        self.invocation_count = 0

    def invoke(self, request: Any) -> ProviderResponse:
        with self._lock:
            self.invocation_count += 1
        self._release_event.wait(timeout=5)
        return _response(request.model_alias)


def _build_orchestrator(
    model_provider: Any,
    *,
    model_health_repository: Any = None,
    idempotency_store: Any = None,
    decision_repository: Any = None,
    clock: Any = None,
) -> InvocationOrchestrator:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    catalogue = InMemoryModelCatalogue([primary, fallback])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    effective_clock = clock or FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=effective_clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        model_health_repository=model_health_repository,
    )
    return InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider,
        clock=effective_clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        idempotency_store=idempotency_store,
        decision_repository=decision_repository,
        model_health_repository=model_health_repository,
    )


# --- High-concurrency idempotency correctness -----------------------------------


def test_fifty_concurrent_duplicate_requests_only_invoke_model_once() -> None:
    release_event = threading.Event()
    provider = BlockingModelProvider(release_event)
    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    orchestrator = _build_orchestrator(provider, idempotency_store=store)
    request = _request(idempotency_key="shared-key")

    thread_count = 50
    barrier = threading.Barrier(thread_count)
    results: dict[int, Any] = {}
    errors: dict[int, Exception] = {}

    def worker(index: int) -> None:
        barrier.wait(timeout=5)  # maximize genuine overlap
        try:
            results[index] = orchestrator.invoke(request)
        except Exception as exc:  # recording for assertion, not handling
            errors[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    # Give every thread a moment to reach the barrier and call reserve() before
    # releasing the blocked invocation.
    import time

    time.sleep(0.3)
    release_event.set()
    for thread in threads:
        thread.join(timeout=5)

    assert provider.invocation_count == 1
    assert len(results) == 1
    assert len(errors) == thread_count - 1
    assert all(isinstance(exc, IdempotencyInProgressError) for exc in errors.values())


# --- Randomized fault injection: bounded fallback, coherent outcomes, no crash ---


def test_two_hundred_sequential_requests_under_random_faults_never_exceed_fallback_bound() -> None:
    provider = RandomFaultModelProvider({"primary": 0.6, "fallback": 0.2}, seed=42)
    orchestrator = _build_orchestrator(provider)

    results = [orchestrator.invoke(_request(conversation_id=f"conv-{i}")) for i in range(200)]

    assert all(len(r.invocation_attempts) <= 2 for r in results)
    assert all(
        attempt.model_alias in ("primary", "fallback")
        for r in results
        for attempt in r.invocation_attempts
    )
    # With these seeded rates, both outcomes are expected to occur at least once —
    # structural invariants, not brittle exact counts.
    assert any(r.decision.fallback_used for r in results)
    assert any(not r.decision.fallback_used and r.response is not None for r in results)
    assert any(r.response is None for r in results)  # both models fail sometimes


def test_concurrent_requests_under_random_faults_never_raise_unexpectedly() -> None:
    provider = RandomFaultModelProvider({"primary": 0.5, "fallback": 0.15}, seed=7)
    orchestrator = _build_orchestrator(provider)

    def worker(index: int) -> Any:
        return orchestrator.invoke(_request(conversation_id=f"conv-{index}"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(worker, range(100)))

    assert len(results) == 100
    assert all(len(r.invocation_attempts) <= 2 for r in results)
    assert all(
        RoutingReasonCode.MODEL_THROTTLED in r.decision.reason_codes
        or RoutingReasonCode.MODEL_UNAVAILABLE in r.decision.reason_codes
        or r.response is not None
        for r in results
    )


# --- Sustained failures: the health signal reduces wasted attempts --------------


def test_sustained_primary_failures_eventually_stop_being_attempted_at_all() -> None:
    health_repository = InMemoryModelHealthRepository(degraded_after=2, unavailable_after=4)
    provider = AlwaysFailModelProvider(failing_alias="primary")
    orchestrator = _build_orchestrator(provider, model_health_repository=health_repository)

    results = [orchestrator.invoke(_request(conversation_id=f"conv-{i}")) for i in range(8)]

    # Early on, primary is still attempted (and fails) before falling back.
    assert results[0].invocation_attempts[0].model_alias == "primary"
    assert results[0].invocation_attempts[0].status == InvocationAttemptStatus.THROTTLED

    # Once primary has accumulated enough consecutive failures, candidate filtering
    # excludes it outright (MODEL_UNHEALTHY) — later requests never even attempt it,
    # going straight to fallback. This is the concrete, observable benefit of the
    # health signal: fewer wasted invocations during a sustained incident.
    last_result = results[-1]
    attempted_aliases = [a.model_alias for a in last_result.invocation_attempts]
    assert "primary" not in attempted_aliases
    assert attempted_aliases == ["fallback"]
    primary_candidate = next(
        c for c in last_result.decision.considered_candidates if c.model_alias == "primary"
    )
    assert primary_candidate.eligible is False
    assert RoutingReasonCode.MODEL_UNHEALTHY in primary_candidate.reason_codes


# --- Throughput sanity (not a precise benchmark — see scripts/benchmark_routing.py) --


def test_five_hundred_sequential_requests_complete_in_a_generous_time_bound() -> None:
    import time

    provider = RandomFaultModelProvider({"primary": 0.1}, seed=1)
    orchestrator = _build_orchestrator(provider)

    started = time.monotonic()
    for i in range(500):
        orchestrator.invoke(_request(conversation_id=f"conv-{i}"))
    elapsed = time.monotonic() - started

    # A generous bound (not a precise benchmark) — this exists to catch an accidental
    # O(n^2) regression or similar, not to measure real performance characteristics.
    assert elapsed < 10.0
