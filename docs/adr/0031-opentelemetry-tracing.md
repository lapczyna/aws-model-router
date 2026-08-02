# ADR-031: OpenTelemetry distributed tracing

## Status
Accepted

## Context
Phase 10b's "operational depth" scope (explicitly requested) also asked for distributed
tracing beyond what AWS X-Ray's existing `Tracing.ACTIVE` setting (Phase 5) already
provides. X-Ray traces the Lambda invocation as a whole (cold start, downstream AWS SDK
calls) but has no concept of *this project's own* logical operations — a routing
decision, an individual fallback-chain invocation attempt — as distinguishable spans.
OpenTelemetry is the vendor-neutral standard for exactly this: application-level spans
that can be exported to any OTLP-compatible backend (Jaeger, Honeycomb, Grafana Tempo, a
self-hosted collector, or AWS's own ADOT collector), independent of X-Ray.

## Decision
`RouteEvaluationService` and `InvocationOrchestrator` each accept an optional
`tracer: opentelemetry.trace.Tracer | None` constructor parameter, defaulting to
`shared.tracing.get_tracer()` (the process-global tracer) when not explicitly injected.

**Why importing `opentelemetry.trace` directly into `src/application/` doesn't violate
ADR-002's "domain/application layers have no AWS SDK imports" rule**: OpenTelemetry's
API package is deliberately vendor-neutral — that is its entire design purpose, the same
reason `boto3` is *not* imported here. It is, in effect, the industry-standard version
of the same dependency-inversion goal `domain.ports` protocols exist for. A project-local
`Tracer` protocol wrapping it was considered and rejected (see Alternatives) as a
redundant abstraction over an abstraction that already exists.

**Spans created**:
* `model_router.evaluate_route` — wraps `RouteEvaluationService.evaluate()` in full
  (renamed internally to `_evaluate`; the public method is now just the span wrapper).
  Attributes: `application_id`, `capability`, and (once computed) `decision_id`,
  `selected_model_alias`, `reason_codes`. Works as a root span on its own — this is what
  `POST /v1/routes/evaluate` produces, since it calls `evaluate()` directly, never
  through `InvocationOrchestrator`.
* `model_router.invoke` — wraps `InvocationOrchestrator.invoke()` in full, including the
  idempotency short-circuit paths. Attributes: `application_id`,
  `has_idempotency_key`, and (once computed) `decision_id`, `selected_model_alias`,
  `fallback_used`, `response_succeeded`.
* `model_router.invoke_attempt` — one child span per candidate in the fallback chain,
  nested under `model_router.invoke` (and containing `model_router.evaluate_route` as a
  sibling, not a child, since evaluation happens once before any attempt). Attributes:
  `model_alias`, `attempt_status`, `latency_ms`.

Every attribute is the same class of sanitized metadata `EmfMetricsPublisher`/
`EventBridgeDecisionEventPublisher` already use — never raw prompt/response content.

**Configuration**: `shared.tracing.configure_tracing(otlp_endpoint=None)` installs a
`TracerProvider`. If `otlp_endpoint` (or the `OTEL_EXPORTER_OTLP_ENDPOINT` environment
variable) is unset, the provider has no span processor attached — spans are still
created (the OpenTelemetry API's own designed-in safe default when unconfigured) but
dropped immediately, never exported. `handlers.api_handler.handler()` calls this once
per cold start, alongside `configure_logging()`. **This project does not deploy or
assume a real OTLP collector** — the same "provision the mechanism, a real backend is a
deploy-time/operator choice" pattern as the OpenAI API key secret (ADR-029) and the SNS
alarm topic subscription (Phase 6). An operator who wants real traces sets
`OTEL_EXPORTER_OTLP_ENDPOINT` on the deployed Lambda (e.g. pointing at a self-hosted
collector, or AWS's ADOT Lambda layer/collector if adopted later — not built here).

## Consequences
* **A real, verified test-isolation hazard, found and fixed during this phase**:
  OpenTelemetry only allows `trace.set_tracer_provider()` to succeed once per process
  (a second call is silently ignored, not replacing the original — confirmed by direct
  experimentation, not assumed). Tests must never call `configure_tracing()` un-patched,
  since doing so would leak a real, sticky global provider into every other test in the
  suite that relies on the *default* tracer — observed directly as background
  `BatchSpanProcessor` export-retry noise bleeding into unrelated test output before the
  fix. `tests/unit/shared/test_tracing.py` patches `trace.set_tracer_provider` to a
  no-op via an autouse fixture; every other test that needs to assert on span behavior
  constructs its own local `TracerProvider` + `InMemorySpanExporter` and injects the
  resulting `Tracer` explicitly (`tests/unit/application/test_tracing_instrumentation.py`)
  — dependency injection sidesteps the global-state problem entirely, the same reason
  `Clock`/`IdentifierGenerator` are injected rather than grabbed from ambient state.
* Tracing is fully optional and additive: every existing call site that doesn't pass
  `tracer=` keeps working exactly as before (`test_no_tracer_injected_uses_a_safe_default_and_never_raises`).
* No CDK/infrastructure change was required — `OTEL_EXPORTER_OTLP_ENDPOINT` is an
  ordinary Lambda environment variable an operator can set via `aws lambda
  update-function-configuration` or by extending `lambda_construct.py`'s environment
  dict themselves; this project doesn't presume a specific collector deployment topology
  to wire against.
* X-Ray (`Tracing.ACTIVE`, Phase 5) and this OpenTelemetry instrumentation are
  independent and complementary, not a replacement of one by the other — X-Ray still
  traces the Lambda invocation/AWS SDK calls; these spans trace this project's own
  logical operations. Unifying them (e.g. via AWS's ADOT SDK extension for
  X-Ray-compatible trace IDs) is a documented possible future step, not built here.

## Alternatives considered
* **A project-local `Tracer` protocol in `domain.ports`, wrapping OpenTelemetry** —
  rejected: OpenTelemetry's API package already *is* the vendor-neutral abstraction;
  wrapping it in a second, project-specific one adds indirection with no real benefit,
  since swapping tracing vendors is already OpenTelemetry's job, not something this
  project would ever need to do independently of it.
* **AWS Distro for OpenTelemetry (ADOT) Lambda layer, full auto-instrumentation** —
  rejected for this phase: requires bundling a collector configuration and wiring
  `AWS_LAMBDA_EXEC_WRAPPER`/layer ARNs per Region into the CDK stack, none of which is
  verifiable without a real deployment and a real collector — inconsistent with this
  project's discipline of everything being testable without live AWS infrastructure.
  Manual instrumentation via the OpenTelemetry SDK directly, with a real (if
  currently-undeployed) OTLP export path, is honestly scoped and fully testable.
* **Wrapping the entire `dispatch()` handler in one top-level span instead of
  service-level spans** — rejected: would lose the ability to distinguish routing time
  from invocation time, and wouldn't produce a root span for `POST /v1/routes/evaluate`
  distinct from `POST /v1/inference`, both of which route through different application
  services today.
