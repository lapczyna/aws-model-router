"""Tests the OpenTelemetry span instrumentation in `RouteEvaluationService` and
`InvocationOrchestrator` (ADR-031) against a real, locally-constructed `TracerProvider`
+ `InMemorySpanExporter` -- never the process-global tracer installed by
`shared.tracing.configure_tracing`, which (per its own docstring) can only be installed
once per process and would make tests interfere with each other.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer

from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ProviderErrorCategory, ProviderName, Role, StopReason
from domain.errors import ProviderError
from domain.fallback import FallbackPolicy
from domain.messages import Message
from domain.provider import ProviderResponse
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


def _tracer_and_exporter() -> tuple[Tracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _response(model_alias: str) -> ProviderResponse:
    return ProviderResponse(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="ok"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=5, output_tokens=5),
    )


def _request() -> InferenceRequest:
    return InferenceRequest(
        application_id="app-1",
        messages=(Message(role=Role.USER, content="hi"),),
        requirements=RoutingRequirements(capability="balanced-text"),
    )


class _SucceedingProvider:
    def invoke(self, request: Any) -> ProviderResponse:
        return _response(request.model_alias)


class _FailThenSucceedProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        self.calls.append(request.model_alias)
        if request.model_alias == "primary":
            raise ProviderError("throttled", category=ProviderErrorCategory.THROTTLED)
        return _response(request.model_alias)


def _build_orchestrator(model_provider: Any, tracer: Tracer) -> InvocationOrchestrator:
    primary = make_model("primary", capability_tags=("balanced-text",))
    fallback = make_model("fallback", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_model_aliases=("primary", "fallback"),
        preferred_model_alias="primary",
        fallback_policy=FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
    )
    catalogue = InMemoryModelCatalogue([primary, fallback])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    clock = FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        tracer=tracer,
    )
    return InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider,
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        tracer=tracer,
    )


def test_successful_invocation_creates_the_three_expected_spans() -> None:
    tracer, exporter = _tracer_and_exporter()
    orchestrator = _build_orchestrator(_SucceedingProvider(), tracer)

    orchestrator.invoke(_request())

    names = [s.name for s in exporter.get_finished_spans()]
    assert "model_router.invoke" in names
    assert "model_router.evaluate_route" in names
    assert "model_router.invoke_attempt" in names


def test_evaluate_route_and_invoke_attempt_are_children_of_invoke() -> None:
    tracer, exporter = _tracer_and_exporter()
    orchestrator = _build_orchestrator(_SucceedingProvider(), tracer)

    orchestrator.invoke(_request())

    spans = {s.name: s for s in exporter.get_finished_spans()}
    invoke_span = spans["model_router.invoke"]
    assert spans["model_router.evaluate_route"].parent is not None
    assert spans["model_router.evaluate_route"].parent.span_id == invoke_span.context.span_id
    assert spans["model_router.invoke_attempt"].parent is not None
    assert spans["model_router.invoke_attempt"].parent.span_id == invoke_span.context.span_id


def test_invoke_span_attributes_reflect_the_final_decision() -> None:
    tracer, exporter = _tracer_and_exporter()
    orchestrator = _build_orchestrator(_SucceedingProvider(), tracer)

    result = orchestrator.invoke(_request())

    invoke_span = next(s for s in exporter.get_finished_spans() if s.name == "model_router.invoke")
    assert invoke_span.attributes is not None
    assert invoke_span.attributes["model_router.application_id"] == "app-1"
    assert invoke_span.attributes["model_router.selected_model_alias"] == "primary"
    assert invoke_span.attributes["model_router.fallback_used"] is False
    assert invoke_span.attributes["model_router.response_succeeded"] is True
    assert invoke_span.attributes["model_router.decision_id"] == result.decision.decision_id


def test_fallback_creates_two_attempt_spans_with_correct_statuses() -> None:
    tracer, exporter = _tracer_and_exporter()
    orchestrator = _build_orchestrator(_FailThenSucceedProvider(), tracer)

    orchestrator.invoke(_request())

    attempt_spans = [
        s for s in exporter.get_finished_spans() if s.name == "model_router.invoke_attempt"
    ]
    assert len(attempt_spans) == 2
    assert attempt_spans[0].attributes is not None
    assert attempt_spans[0].attributes["model_router.model_alias"] == "primary"
    assert attempt_spans[0].attributes["model_router.attempt_status"] == "throttled"
    assert attempt_spans[1].attributes is not None
    assert attempt_spans[1].attributes["model_router.model_alias"] == "fallback"
    assert attempt_spans[1].attributes["model_router.attempt_status"] == "succeeded"


def test_no_eligible_model_creates_no_attempt_span() -> None:
    tracer, exporter = _tracer_and_exporter()
    primary = make_model("primary", capability_tags=("balanced-text",))
    policy = make_policy(
        allowed_capabilities=("economical-text",), allowed_model_aliases=("primary",)
    )
    catalogue = InMemoryModelCatalogue([primary])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    clock = FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        tracer=tracer,
    )
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=_SucceedingProvider(),
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        tracer=tracer,
    )

    orchestrator.invoke(_request())

    names = [s.name for s in exporter.get_finished_spans()]
    assert "model_router.invoke" in names
    assert "model_router.evaluate_route" in names
    assert "model_router.invoke_attempt" not in names


def test_route_evaluation_service_used_standalone_is_a_root_span() -> None:
    """POST /v1/routes/evaluate calls RouteEvaluationService.evaluate() directly, never
    through InvocationOrchestrator -- confirms evaluate_route's span works as a root
    span on its own, not just when nested inside invoke."""
    tracer, exporter = _tracer_and_exporter()
    primary = make_model("primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("primary",), preferred_model_alias="primary")
    catalogue = InMemoryModelCatalogue([primary])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=FixedClock(FIXED_NOW),
        identifier_generator=Uuid4IdentifierGenerator(),
        tracer=tracer,
    )

    route_service.evaluate(_request())

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "model_router.evaluate_route"
    assert spans[0].parent is None


def test_no_tracer_injected_uses_a_safe_default_and_never_raises() -> None:
    """Neither service requires an explicit tracer -- both must work exactly as before
    OpenTelemetry existed if a caller doesn't pass one."""
    primary = make_model("primary", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("primary",), preferred_model_alias="primary")
    catalogue = InMemoryModelCatalogue([primary])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=FixedClock(FIXED_NOW),
        identifier_generator=Uuid4IdentifierGenerator(),
    )
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=_SucceedingProvider(),
        clock=FixedClock(FIXED_NOW),
        identifier_generator=Uuid4IdentifierGenerator(),
    )

    result = orchestrator.invoke(_request())

    assert result.response is not None
