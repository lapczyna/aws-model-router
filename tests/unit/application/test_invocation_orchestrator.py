"""Unit tests for `InvocationOrchestrator`: fallback, idempotency, and final decision
aggregation, using a hand-rolled `FakeModelProvider` and the real (in-memory)
`InMemoryIdempotencyStore` so concurrency/expiry behavior is genuinely exercised, not
mocked away.
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ModelHealthStatus, ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import IdempotencyConflictError, IdempotencyInProgressError, ProviderError
from domain.fallback import FallbackPolicy
from domain.invocation import InvocationAttemptStatus
from domain.messages import Message
from domain.policy import IdempotencyPolicy
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements
from domain.usage import Usage
from tests.support.fakes import (
    FixedClock,
    InMemoryModelCatalogue,
    InMemoryRoutingPolicyRepository,
    SequentialIdentifierGenerator,
    make_model,
    make_policy,
)

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _MutableClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class FakeModelProvider:
    """Returns/raises each queued item in order, per model_alias. An empty queue for a
    requested alias raises `AssertionError` — a loud failure if the orchestrator invokes
    a model the test didn't expect it to reach."""

    def __init__(self, responses: dict[str, list[ProviderResponse | Exception]]) -> None:
        self._responses = {alias: list(items) for alias, items in responses.items()}
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        self.calls.append(request.model_alias)
        queue = self._responses.get(request.model_alias)
        if not queue:
            raise AssertionError(
                f"FakeModelProvider: no more responses for {request.model_alias!r}"
            )
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(model_alias: str, content: str = "ok") -> ProviderResponse:
    return ProviderResponse(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content=content),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=5, output_tokens=5),
    )


def _request(
    application_id: str = "app-1",
    idempotency_key: str | None = None,
    conversation_id: str | None = None,
    content: str = "hello",
) -> InferenceRequest:
    return InferenceRequest(
        application_id=application_id,
        messages=(Message(role=Role.USER, content=content),),
        requirements=RoutingRequirements(capability="balanced-text"),
        idempotency_key=idempotency_key,
        conversation_id=conversation_id,
    )


def _build_orchestrator(
    catalogue: InMemoryModelCatalogue,
    policy_repository: InMemoryRoutingPolicyRepository,
    model_provider: Any,
    idempotency_store: Any = None,
    clock: Any = None,
    decision_repository: Any = None,
    model_health_repository: Any = None,
    metrics_publisher: Any = None,
    decision_event_publisher: Any = None,
) -> InvocationOrchestrator:
    effective_clock = clock or FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=effective_clock,
        identifier_generator=SequentialIdentifierGenerator(),
        model_health_repository=model_health_repository,
    )
    return InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider,
        clock=effective_clock,
        identifier_generator=SequentialIdentifierGenerator(),
        idempotency_store=idempotency_store,
        decision_repository=decision_repository,
        model_health_repository=model_health_repository,
        metrics_publisher=metrics_publisher,
        decision_event_publisher=decision_event_publisher,
        monotonic=lambda: 0.0,
    )


def test_primary_succeeds() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.decision.selected_model_alias == "model-a"
    assert result.decision.fallback_used is False
    assert result.response is not None
    assert [a.model_alias for a in result.invocation_attempts] == ["model-a"]
    assert result.invocation_attempts[0].status == InvocationAttemptStatus.SUCCEEDED


def test_primary_throttled_and_fallback_succeeds() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "fallback": [_response("fallback")],
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.decision.selected_model_alias == "fallback"
    assert result.decision.fallback_used is True
    assert RoutingReasonCode.MODEL_THROTTLED in result.decision.reason_codes
    assert RoutingReasonCode.FALLBACK_SELECTED in result.decision.reason_codes
    assert [a.model_alias for a in result.invocation_attempts] == ["primary", "fallback"]
    assert result.invocation_attempts[0].status == InvocationAttemptStatus.THROTTLED
    assert result.invocation_attempts[1].status == InvocationAttemptStatus.SUCCEEDED


def test_primary_transient_failure_and_fallback_succeeds() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("transient", category=ProviderErrorCategory.TRANSIENT)],
            "fallback": [_response("fallback")],
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.decision.selected_model_alias == "fallback"
    assert result.decision.fallback_used is True
    assert RoutingReasonCode.MODEL_UNAVAILABLE in result.decision.reason_codes
    assert result.invocation_attempts[0].status == InvocationAttemptStatus.TRANSIENT_ERROR


def test_non_retryable_failure_does_not_fallback() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider(
        {"primary": [ProviderError("bad request", category=ProviderErrorCategory.PERMANENT)]}
        # "fallback" deliberately has no queued responses: if reached, the fake raises.
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.decision.selected_model_alias is None
    assert result.response is None
    assert [a.model_alias for a in result.invocation_attempts] == ["primary"]
    assert result.invocation_attempts[0].status == InvocationAttemptStatus.NON_RETRYABLE_ERROR


def test_fallback_limit_enforced() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback1 = make_model("fallback1", capability_tags=("balanced-text",))
    fallback2 = make_model("fallback2", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback1", "fallback2"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(
            fallback_model_aliases=("fallback1", "fallback2"), maximum_attempts=2
        ),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "fallback1": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            # "fallback2" deliberately has no responses — maximum_attempts=2 must stop
            # the chain at ["primary", "fallback1"] without ever reaching it.
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback1, fallback2]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert [a.model_alias for a in result.invocation_attempts] == ["primary", "fallback1"]
    assert result.decision.selected_model_alias is None


def test_fallback_skips_candidates_ineligible_on_cost() -> None:
    primary = make_model(
        "primary",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    expensive_fallback = make_model(
        "expensive-fallback",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="100",
        output_price_per_1k_tokens="100",
    )
    cheap_fallback = make_model(
        "cheap-fallback",
        capability_tags=("balanced-text",),
        input_price_per_1k_tokens="0.001",
        output_price_per_1k_tokens="0.001",
    )
    policy = make_policy(
        allowed_model_aliases=("primary", "expensive-fallback", "cheap-fallback"),
        preferred_model_alias="primary",
        maximum_estimated_cost_usd="0.01",
        fallback_policy=FallbackPolicy(
            fallback_model_aliases=("expensive-fallback", "cheap-fallback"), maximum_attempts=3
        ),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "cheap-fallback": [_response("cheap-fallback")],
            # "expensive-fallback" has no responses — it is cost-ineligible and must be
            # skipped entirely, never invoked.
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, expensive_fallback, cheap_fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert [a.model_alias for a in result.invocation_attempts] == ["primary", "cheap-fallback"]
    assert result.decision.selected_model_alias == "cheap-fallback"


def test_all_eligible_models_fail() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "fallback": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.decision.selected_model_alias is None
    assert result.response is None
    assert [a.model_alias for a in result.invocation_attempts] == ["primary", "fallback"]
    assert all(a.status == InvocationAttemptStatus.THROTTLED for a in result.invocation_attempts)


def test_audit_attempts_are_correctly_ordered_across_three_candidates() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback1 = make_model("fallback1", capability_tags=("balanced-text",))
    fallback2 = make_model("fallback2", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback1", "fallback2"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(
            fallback_model_aliases=("fallback1", "fallback2"), maximum_attempts=3
        ),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "fallback1": [ProviderError("transient", category=ProviderErrorCategory.TRANSIENT)],
            "fallback2": [_response("fallback2")],
        }
    )
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback1, fallback2]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert [a.model_alias for a in result.invocation_attempts] == [
        "primary",
        "fallback1",
        "fallback2",
    ]
    assert [a.status for a in result.invocation_attempts] == [
        InvocationAttemptStatus.THROTTLED,
        InvocationAttemptStatus.TRANSIENT_ERROR,
        InvocationAttemptStatus.SUCCEEDED,
    ]


def test_no_eligible_model_returns_early_without_any_invocation() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_capabilities=("economical-text",), allowed_model_aliases=("model-a",)
    )
    provider = FakeModelProvider({})
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())  # requests "balanced-text"; policy denies it

    assert result.decision.selected_model_alias is None
    assert result.response is None
    assert result.invocation_attempts == ()
    assert provider.calls == []


def test_fallback_used_when_preferred_model_is_excluded_by_health_before_selection() -> None:
    """Regression test: `PreferredModelStrategy` deliberately leaves
    `selected_model_alias` unset when the preferred model is ineligible (e.g.
    health-excluded) rather than implicitly substituting -- but the orchestrator's
    fallback chain must still pick up a healthy, policy-approved fallback model in that
    case. Before this fix, `_invoke_uncached` short-circuited on `selected_model_alias
    is None` and never even considered the fallback chain, so a sustained primary
    incident caused total request failure despite a healthy fallback model being
    available -- defeating the point of tracking model health at all.
    """
    from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository

    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider({"fallback": [_response("fallback")]})
    health_repository = InMemoryModelHealthRepository(degraded_after=2, unavailable_after=3)
    for _ in range(3):
        health_repository.record_outcome("primary", InvocationAttemptStatus.THROTTLED)
    assert health_repository.get_health("primary") is ModelHealthStatus.UNAVAILABLE

    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        model_health_repository=health_repository,
    )

    result = orchestrator.invoke(_request())

    assert provider.calls == ["fallback"]  # primary is never even attempted
    assert result.response is not None
    assert result.decision.selected_model_alias == "fallback"
    assert result.decision.fallback_used is True
    assert RoutingReasonCode.NO_ELIGIBLE_MODEL not in result.decision.reason_codes


def test_fallback_can_replace_a_health_excluded_experiment_arm_but_marks_it_auditable() -> None:
    """Characterization test (found during Phase 9's multi-perspective self-review, not
    the original fault-injection pass): the ADR-028 fix applies uniformly regardless of
    routing strategy, so a policy combining `routing_strategy: experiment` with a
    configured `fallback_policy` can have its assigned arm replaced by a fallback model
    if that arm becomes health-excluded -- exactly the substitution
    `ExperimentStrategy`'s own docstring says the *strategy* never performs itself. This
    is accepted, not a bug, because it is never silent end-to-end: `fallback_used` and
    `FALLBACK_SELECTED` are always set, so experiment analysis requiring strict arm
    purity can filter on `fallback_used`. See ADR-028's "Interaction with
    ExperimentStrategy".
    """
    from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository
    from domain.experiment import ExperimentArm, ExperimentPolicy

    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    # "demo-app" + "conv-1" deterministically assigns to "primary" at these weights.
    experiment_policy = ExperimentPolicy(
        experiment_id="exp1",
        arms=(
            ExperimentArm(model_alias="primary", weight=70),
            ExperimentArm(model_alias="fallback", weight=30),
        ),
    )
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        routing_strategy="experiment",
        experiment_policy=experiment_policy,
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider({"fallback": [_response("fallback")]})
    health_repository = InMemoryModelHealthRepository(degraded_after=2, unavailable_after=3)
    for _ in range(3):
        health_repository.record_outcome("primary", InvocationAttemptStatus.THROTTLED)
    assert health_repository.get_health("primary") is ModelHealthStatus.UNAVAILABLE

    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        model_health_repository=health_repository,
    )

    result = orchestrator.invoke(_request(application_id="demo-app", conversation_id="conv-1"))

    assert provider.calls == ["fallback"]  # the assigned "primary" arm is never attempted
    assert result.decision.selected_model_alias == "fallback"
    assert result.decision.fallback_used is True
    assert RoutingReasonCode.FALLBACK_SELECTED in result.decision.reason_codes


def test_repeated_idempotent_request_returns_cached_result_without_reinvoking() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        idempotency_policy=IdempotencyPolicy(allow_response_caching=True, retention_seconds=300),
    )
    provider = FakeModelProvider({"model-a": [_response("model-a")]})  # exactly one response
    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        idempotency_store=store,
    )
    request = _request(idempotency_key="key-1")

    first = orchestrator.invoke(request)
    second = orchestrator.invoke(request)

    assert provider.calls == ["model-a"]  # only ever invoked once
    assert first.response is not None
    assert second.response is not None
    assert second.decision.decision_id == first.decision.decision_id


def test_idempotency_conflict_raised_for_same_key_different_content() -> None:
    # Conflict detection requires a still-live record to conflict against. With the
    # default (non-caching) policy, completing a request immediately releases its
    # record — a later request with the same key then has nothing to conflict with
    # and is correctly treated as brand new. Caching keeps the record alive so this
    # scenario is meaningful to test.
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        idempotency_policy=IdempotencyPolicy(allow_response_caching=True, retention_seconds=300),
    )
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        idempotency_store=store,
    )

    orchestrator.invoke(_request(idempotency_key="key-1", content="hello"))

    with pytest.raises(IdempotencyConflictError):
        orchestrator.invoke(_request(idempotency_key="key-1", content="different content"))


def test_expired_idempotency_record_allows_reinvocation() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        idempotency_policy=IdempotencyPolicy(allow_response_caching=True, retention_seconds=1),
    )
    provider = FakeModelProvider(
        {"model-a": [_response("model-a", content="first"), _response("model-a", content="second")]}
    )
    clock = _MutableClock(FIXED_NOW)
    store = InMemoryIdempotencyStore(clock=clock)
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        idempotency_store=store,
        clock=clock,
    )
    request = _request(idempotency_key="key-1")

    first = orchestrator.invoke(request)
    clock.advance(2)  # past retention_seconds=1
    second = orchestrator.invoke(request)

    assert provider.calls == ["model-a", "model-a"]
    assert first.response is not None
    assert second.response is not None
    assert first.response.message.content == "first"
    assert second.response.message.content == "second"


def test_idempotency_reservation_is_released_on_unexpected_failure() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")

    class _ExplodingProvider:
        def invoke(self, request: Any) -> ProviderResponse:
            raise RuntimeError("boom")

    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        _ExplodingProvider(),
        idempotency_store=store,
    )
    request = _request(idempotency_key="key-1")

    with pytest.raises(RuntimeError):
        orchestrator.invoke(request)

    # The reservation must have been released, not left stuck "in progress" — a second
    # attempt (with a working provider this time) should proceed as NEW, not raise
    # IdempotencyInProgressError.
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    orchestrator2 = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        idempotency_store=store,
    )
    result = orchestrator2.invoke(request)
    assert result.response is not None


def test_concurrent_duplicate_requests_only_invoke_model_once() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    release_event = threading.Event()
    invoke_lock = threading.Lock()
    invocation_count = 0

    class BlockingModelProvider:
        def invoke(self, request: Any) -> ProviderResponse:
            nonlocal invocation_count
            with invoke_lock:
                invocation_count += 1
            release_event.wait(timeout=5)
            return _response("model-a")

    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        BlockingModelProvider(),
        idempotency_store=store,
    )
    request = _request(idempotency_key="key-1")

    results: dict[str, Any] = {}
    errors: dict[str, Exception] = {}

    def worker(name: str) -> None:
        try:
            results[name] = orchestrator.invoke(request)
        except Exception as exc:
            errors[name] = exc

    first_thread = threading.Thread(target=worker, args=("first",))
    second_thread = threading.Thread(target=worker, args=("second",))

    first_thread.start()
    time.sleep(0.1)  # let the first thread reserve the key and block inside invoke()
    second_thread.start()
    time.sleep(0.1)  # let the second thread's reserve() observe IN_PROGRESS
    release_event.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert invocation_count == 1
    assert "first" in results
    assert "second" in errors
    assert isinstance(errors["second"], IdempotencyInProgressError)


def test_result_is_persisted_when_a_decision_repository_is_configured() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    decision_repository = InMemoryRoutingDecisionRepository()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        decision_repository=decision_repository,
    )

    result = orchestrator.invoke(_request())

    stored = decision_repository.get(result.decision.decision_id)
    assert stored is not None
    assert stored.decision == result.decision
    assert stored.invocation_attempts == result.invocation_attempts


class _RecordingHealthRepository:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, InvocationAttemptStatus]] = []

    def get_health(self, model_alias: str) -> ModelHealthStatus:
        return ModelHealthStatus.HEALTHY

    def record_outcome(self, model_alias: str, status: InvocationAttemptStatus) -> None:
        self.outcomes.append((model_alias, status))


class _RecordingMetricsPublisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, result: Any) -> None:
        self.published.append(result)


class _RecordingDecisionEventPublisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, result: Any) -> None:
        self.published.append(result)


def test_health_outcome_recorded_for_each_invocation_attempt() -> None:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    provider = FakeModelProvider(
        {
            "primary": [ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)],
            "fallback": [_response("fallback")],
        }
    )
    health_repository = _RecordingHealthRepository()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([primary, fallback]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        model_health_repository=health_repository,
    )

    orchestrator.invoke(_request())

    assert health_repository.outcomes == [
        ("primary", InvocationAttemptStatus.THROTTLED),
        ("fallback", InvocationAttemptStatus.SUCCEEDED),
    ]


def test_metrics_published_once_per_completed_invocation() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    metrics_publisher = _RecordingMetricsPublisher()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        metrics_publisher=metrics_publisher,
    )

    result = orchestrator.invoke(_request())

    assert len(metrics_publisher.published) == 1
    assert metrics_publisher.published[0] is result


def test_metrics_published_even_when_no_eligible_model() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_capabilities=("economical-text",), allowed_model_aliases=("model-a",)
    )
    metrics_publisher = _RecordingMetricsPublisher()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        FakeModelProvider({}),
        metrics_publisher=metrics_publisher,
    )

    orchestrator.invoke(_request())

    assert len(metrics_publisher.published) == 1
    assert metrics_publisher.published[0].decision.selected_model_alias is None


def test_decision_event_published_once_per_completed_invocation() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    decision_event_publisher = _RecordingDecisionEventPublisher()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
        decision_event_publisher=decision_event_publisher,
    )

    result = orchestrator.invoke(_request())

    assert len(decision_event_publisher.published) == 1
    assert decision_event_publisher.published[0] is result


def test_decision_event_published_even_when_no_eligible_model() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_capabilities=("economical-text",), allowed_model_aliases=("model-a",)
    )
    decision_event_publisher = _RecordingDecisionEventPublisher()
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        FakeModelProvider({}),
        decision_event_publisher=decision_event_publisher,
    )

    orchestrator.invoke(_request())

    assert len(decision_event_publisher.published) == 1
    assert decision_event_publisher.published[0].decision.selected_model_alias is None


def test_no_decision_event_publisher_configured_does_not_error() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    orchestrator = _build_orchestrator(
        InMemoryModelCatalogue([model]),
        InMemoryRoutingPolicyRepository(default_policy=policy),
        provider,
    )

    result = orchestrator.invoke(_request())

    assert result.response is not None
