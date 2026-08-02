#!/usr/bin/env python
"""Run the demo scenarios that need a scripted, narrated walkthrough rather than a
single static example file: model-invocation fallback, idempotent duplicate requests,
model health degradation, observability (structured logs + EMF metrics for one
request), and cross-provider fallback (Phase 10a). No AWS credentials required --
everything here uses in-process fakes, the same pattern as
`tests/unit/application/test_invocation_orchestrator.py`.

See `docs/demonstrations.md` for all sample demonstrations, including the ones that
already have a dedicated existing script/fixture and don't need a new one here.

Usage:
    python scripts/run_demo_scenarios.py                      # run all scenarios
    python scripts/run_demo_scenarios.py --scenario fallback
    python scripts/run_demo_scenarios.py --scenario idempotency
    python scripts/run_demo_scenarios.py --scenario health-degradation
    python scripts/run_demo_scenarios.py --scenario observability
    python scripts/run_demo_scenarios.py --scenario multi-provider-fallback
    python scripts/run_demo_scenarios.py --scenario decision-events
    python scripts/run_demo_scenarios.py --scenario tracing
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from adapters.composite_model_provider import CompositeModelProvider
from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository
from adapters.metrics.emf_metrics_publisher import EmfMetricsPublisher
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.catalogue import ModelCapabilities, ModelDefinition, ModelPricing, ModelResolution
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import (
    LatencyPreference,
    ModelResolutionType,
    ProviderErrorCategory,
    ProviderName,
    QualityTier,
    Role,
    StopReason,
)
from domain.errors import ProviderError, RoutingPolicyNotFoundError
from domain.fallback import FallbackPolicy
from domain.messages import Message
from domain.policy import IdempotencyPolicy, RoutingPolicy
from domain.provider import ProviderResponse
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements
from domain.usage import Usage
from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator
from shared.structured_logging import configure_logging


@dataclass
class _InMemoryModelCatalogue:
    """Minimal, self-contained `domain.ports.ModelCatalogue` -- deliberately not
    imported from `tests.support.fakes`, since this script must run standalone, outside
    the pytest path configuration.
    """

    models: Sequence[ModelDefinition]
    version: int = 1

    @property
    def catalogue_version(self) -> int:
        return self.version

    def find_by_capability(self, capability: str) -> Sequence[ModelDefinition]:
        return tuple(m for m in self.models if capability in m.capabilities.capability_tags)

    def get_by_alias(self, model_alias: str) -> ModelDefinition | None:
        return next((m for m in self.models if m.model_alias == model_alias), None)

    def all_models(self) -> Sequence[ModelDefinition]:
        return tuple(self.models)


@dataclass
class _InMemoryRoutingPolicyRepository:
    """Minimal, self-contained `domain.ports.RoutingPolicyRepository`."""

    policies_by_application: dict[str, RoutingPolicy] = field(default_factory=dict)
    default_policy: RoutingPolicy | None = None

    def resolve(self, application_id: str) -> RoutingPolicy:
        if application_id in self.policies_by_application:
            return self.policies_by_application[application_id]
        if self.default_policy is not None:
            return self.default_policy
        raise RoutingPolicyNotFoundError(f"No routing policy found for '{application_id}'")


def _make_model(model_alias: str, provider: ProviderName = ProviderName.BEDROCK) -> ModelDefinition:
    return ModelDefinition(
        model_alias=model_alias,
        provider=provider,
        region="us-east-1",
        resolution=ModelResolution(
            type=ModelResolutionType.DIRECT_MODEL_ID, value=f"fake.{model_alias}-v1:0"
        ),
        capabilities=ModelCapabilities(
            capability_tags=("balanced-text",),
            quality_tier=QualityTier.STANDARD,
            max_input_tokens=200_000,
            max_output_tokens=4096,
            supports_tool_use=False,
            supports_structured_output=False,
            supports_streaming=True,
            typical_latency=LatencyPreference.BALANCED,
        ),
        pricing=ModelPricing(
            input_price_per_1k_tokens=Decimal("0.003"),
            output_price_per_1k_tokens=Decimal("0.015"),
            pricing_version=1,
        ),
    )


def _banner(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _response(
    model_alias: str, text: str = "ok", provider: ProviderName = ProviderName.BEDROCK
) -> ProviderResponse:
    return ProviderResponse(
        model_alias=model_alias,
        provider=provider,
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=5, output_tokens=5),
    )


def _request(idempotency_key: str | None = None) -> InferenceRequest:
    return InferenceRequest(
        application_id="demo-app",
        messages=(Message(role=Role.USER, content="What are your support hours?"),),
        requirements=RoutingRequirements(capability="balanced-text"),
        idempotency_key=idempotency_key,
    )


def _demo_policy(**overrides: Any) -> RoutingPolicy:
    defaults: dict[str, Any] = {
        "policy_id": "demo-policy",
        "policy_version": 1,
        "allowed_capabilities": ("balanced-text",),
        "allowed_model_aliases": ("primary", "fallback"),
        "allowed_quality_tiers": (QualityTier.STANDARD,),
        "default_quality_tier": QualityTier.STANDARD,
        "maximum_estimated_cost_usd": "0.50",
        "maximum_output_tokens": 1000,
        "preferred_model_alias": "primary",
        "routing_strategy": "preferred_model",
        "fallback_policy": FallbackPolicy(fallback_model_aliases=("fallback",), maximum_attempts=2),
        "idempotency_policy": IdempotencyPolicy(allow_response_caching=True, retention_seconds=300),
    }
    defaults.update(overrides)
    return RoutingPolicy(**defaults)


def _build_orchestrator(
    model_provider: Any,
    *,
    model_health_repository: Any = None,
    idempotency_store: Any = None,
    decision_repository: Any = None,
    metrics_publisher: Any = None,
    decision_event_publisher: Any = None,
    tracer: Any = None,
) -> InvocationOrchestrator:
    primary = _make_model("primary")
    fallback = _make_model("fallback")
    catalogue = _InMemoryModelCatalogue([primary, fallback])
    policy_repository = _InMemoryRoutingPolicyRepository(default_policy=_demo_policy())
    clock = SystemClock()
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        model_health_repository=model_health_repository,
        tracer=tracer,
    )
    return InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider,
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
        idempotency_store=idempotency_store,
        decision_repository=decision_repository,
        model_health_repository=model_health_repository,
        metrics_publisher=metrics_publisher,
        decision_event_publisher=decision_event_publisher,
        tracer=tracer,
    )


class _FailThenSucceedProvider:
    """Primary always throttles; fallback always succeeds."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        self.calls.append(request.model_alias)
        if request.model_alias == "primary":
            raise ProviderError("simulated throttling", category=ProviderErrorCategory.THROTTLED)
        return _response(request.model_alias)


class _CountingSuccessProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        self.calls.append(request.model_alias)
        return _response(request.model_alias)


class _AlwaysFailPrimaryProvider:
    def invoke(self, request: Any) -> ProviderResponse:
        if request.model_alias == "primary":
            raise ProviderError(
                "simulated sustained throttling", category=ProviderErrorCategory.THROTTLED
            )
        return _response(request.model_alias)


def demo_fallback() -> None:
    _banner("Demo 2: model-invocation fallback on provider failure")
    provider = _FailThenSucceedProvider()
    orchestrator = _build_orchestrator(provider)

    result = orchestrator.invoke(_request())

    print(
        f"Invocation attempts: {[(a.model_alias, a.status.value) for a in result.invocation_attempts]}"
    )
    print(f"Final selected model: {result.decision.selected_model_alias}")
    print(f"fallback_used: {result.decision.fallback_used}")
    print(f"reason_codes: {[c.value for c in result.decision.reason_codes]}")
    print(f"Response text: {result.response.message.content if result.response else None}")
    assert result.decision.selected_model_alias == "fallback"
    assert result.decision.fallback_used is True
    print("\n-> Primary was throttled; the router automatically retried the policy's")
    print("   configured fallback model and returned a successful response. See ADR-011.")


def demo_idempotency() -> None:
    _banner("Demo 4: idempotent duplicate request")
    provider = _CountingSuccessProvider()
    store = InMemoryIdempotencyStore(clock=SystemClock())
    orchestrator = _build_orchestrator(provider, idempotency_store=store)
    request = _request(idempotency_key="demo-idempotency-key-001")

    first = orchestrator.invoke(request)
    second = orchestrator.invoke(request)

    print(f"Real model invocations made: {len(provider.calls)}")
    print(f"First call decision_id:  {first.decision.decision_id}")
    print(f"Second call decision_id: {second.decision.decision_id}")
    assert len(provider.calls) == 1
    assert first.decision.decision_id == second.decision.decision_id
    print("\n-> Same idempotency_key, same request body: the second call returned the")
    print("   cached result from the first, without invoking the model again. See ADR-013.")


def demo_health_degradation() -> None:
    _banner("Demo 6: model health degradation")
    health_repository = InMemoryModelHealthRepository(degraded_after=2, unavailable_after=3)
    provider = _AlwaysFailPrimaryProvider()
    orchestrator = _build_orchestrator(provider, model_health_repository=health_repository)

    for i in range(1, 6):
        result = orchestrator.invoke(_request())
        attempted = [a.model_alias for a in result.invocation_attempts]
        health = health_repository.get_health("primary")
        print(
            f"Request {i}: primary health={health.value:<11} "
            f"attempted={attempted} selected={result.decision.selected_model_alias}"
        )

    print("\n-> After enough consecutive failures, `primary` is marked UNAVAILABLE and")
    print("   later requests skip it entirely -- no wasted invocation -- while still")
    print("   recovering via the healthy `fallback` model. See ADR-020 and ADR-028 (the")
    print("   latter fixed a real gap Phase 9's fault-injection testing found: before")
    print("   it, a health-excluded preferred model caused total failure instead of")
    print("   falling back).")


def demo_observability() -> None:
    _banner("Demo 8: observability -- structured logs and EMF metrics for one request")
    configure_logging(level="INFO")
    logger = logging.getLogger("scripts.run_demo_scenarios")

    provider = _CountingSuccessProvider()
    decision_repository = InMemoryRoutingDecisionRepository()
    metrics_publisher = EmfMetricsPublisher(environment="demo")
    orchestrator = _build_orchestrator(
        provider, decision_repository=decision_repository, metrics_publisher=metrics_publisher
    )

    print("--- structured JSON log line (what CloudWatch Logs would capture) ---")
    result = orchestrator.invoke(_request())
    logger.info(
        "Demo inference request completed",
        extra={
            "request_id": "demo-request-001",
            "decision_id": result.decision.decision_id,
            "application_id": result.decision.application_id,
            "model_alias": result.decision.selected_model_alias,
        },
    )
    print("--- EMF metric lines were printed above by EmfMetricsPublisher.publish() ---")
    audit_record = decision_repository.get(result.decision.decision_id)
    print(
        f"\nPersisted audit record found: {audit_record is not None} (decision_id={result.decision.decision_id})"
    )
    print("\n-> Every metric/log line above is metadata only (decision IDs, model alias,")
    print("   status, cost estimate) -- never raw prompt/response content. See ADR-008,")
    print("   ADR-019, and docs/operations/observability.md.")


class _BedrockFailsOpenAiSucceedsProvider:
    """A fake `CompositeModelProvider` sub-provider stand-in: fails whatever it's asked
    to invoke. Paired with `_CountingSuccessProvider` under a real
    `CompositeModelProvider`, dispatched to by `model.provider` -- this exercises the
    actual dispatch logic (ADR-029), not just two fakes called directly."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, request: Any) -> ProviderResponse:
        self.calls.append(request.model_alias)
        raise ProviderError(
            "simulated Bedrock throttling", category=ProviderErrorCategory.THROTTLED
        )


def demo_multi_provider_fallback() -> None:
    _banner("Demo: cross-provider fallback (Bedrock primary, OpenAI fallback)")
    bedrock_model = _make_model("bedrock-primary", provider=ProviderName.BEDROCK)
    openai_model = _make_model("openai-fallback", provider=ProviderName.OPENAI)
    catalogue = _InMemoryModelCatalogue([bedrock_model, openai_model])
    policy = _demo_policy(
        allowed_model_aliases=("bedrock-primary", "openai-fallback"),
        preferred_model_alias="bedrock-primary",
        fallback_policy=FallbackPolicy(
            fallback_model_aliases=("openai-fallback",), maximum_attempts=2
        ),
    )
    policy_repository = _InMemoryRoutingPolicyRepository(default_policy=policy)
    clock = SystemClock()
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
    )
    bedrock_provider = _BedrockFailsOpenAiSucceedsProvider()
    openai_provider = _CountingSuccessProvider()
    composite = CompositeModelProvider(
        model_catalogue=catalogue,
        providers={ProviderName.BEDROCK: bedrock_provider, ProviderName.OPENAI: openai_provider},
    )
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=composite,
        clock=clock,
        identifier_generator=Uuid4IdentifierGenerator(),
    )

    result = orchestrator.invoke(_request())

    print(f"Bedrock sub-provider was called with: {bedrock_provider.calls}")
    print(f"OpenAI sub-provider was called with:  {openai_provider.calls}")
    print(f"Final selected model: {result.decision.selected_model_alias}")
    print(f"fallback_used: {result.decision.fallback_used}")
    assert bedrock_provider.calls == ["bedrock-primary"]
    assert openai_provider.calls == ["openai-fallback"]
    assert result.decision.selected_model_alias == "openai-fallback"
    print("\n-> A single fallback chain spanned two different providers.")
    print("   CompositeModelProvider dispatched each attempt to the correct adapter")
    print("   based on the catalogued model's `provider` field, and neither provider")
    print("   adapter had any awareness the other exists. See ADR-002 and ADR-029.")


class _FakeEventBridgeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_events(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "evt-demo"}]}


def demo_decision_events() -> None:
    _banner("Demo: EventBridge decision events (Phase 10b, ADR-030)")
    import json

    from adapters.events.eventbridge_decision_event_publisher import (
        EventBridgeDecisionEventPublisher,
    )

    fake_client = _FakeEventBridgeClient()
    publisher = EventBridgeDecisionEventPublisher(client=fake_client, event_bus_name="demo-bus")  # type: ignore[arg-type]
    provider = _CountingSuccessProvider()
    orchestrator = _build_orchestrator(provider, decision_event_publisher=publisher)

    orchestrator.invoke(_request())

    print(f"Events published to EventBridge: {len(fake_client.calls)}")
    detail = json.loads(fake_client.calls[0]["Entries"][0]["Detail"])
    print(json.dumps(detail, indent=2))
    print("\n-> The event's Detail is metadata only -- decision/policy IDs, capability,")
    print("   selected model, cost -- never raw prompt/response content. An external")
    print("   system can subscribe to this bus instead of polling")
    print("   GET /v1/decisions/{decisionId}. See ADR-030.")


def demo_tracing() -> None:
    _banner("Demo: OpenTelemetry distributed tracing (Phase 10b, ADR-031)")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("demo")

    orchestrator = _build_orchestrator(_FailThenSucceedProvider(), tracer=tracer)
    orchestrator.invoke(_request())

    print("Spans created for one request (with a fallback):")
    for span in exporter.get_finished_spans():
        indent = "  " if span.parent is not None else ""
        attrs = dict(span.attributes or {})
        print(f"{indent}- {span.name}  {attrs}")
    print("\n-> Every span attribute is sanitized metadata (application_id, capability,")
    print("   model_alias, status, latency) -- never raw prompt/response content. No")
    print("   real OTLP collector is deployed by this project; set")
    print("   OTEL_EXPORTER_OTLP_ENDPOINT to export these spans somewhere real. See")
    print("   ADR-031.")


_SCENARIOS = {
    "fallback": demo_fallback,
    "idempotency": demo_idempotency,
    "health-degradation": demo_health_degradation,
    "observability": demo_observability,
    "multi-provider-fallback": demo_multi_provider_fallback,
    "decision-events": demo_decision_events,
    "tracing": demo_tracing,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(_SCENARIOS),
        help="Run only this scenario (default: run all four in order)",
    )
    args = parser.parse_args(argv)

    scenarios = [_SCENARIOS[args.scenario]] if args.scenario else list(_SCENARIOS.values())
    for scenario in scenarios:
        scenario()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
