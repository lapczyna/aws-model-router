"""OpenTelemetry tracing configuration (ADR-031, Phase 10b).

Application/adapter code always calls the OpenTelemetry *API* directly (`get_tracer`,
`start_as_current_span`) -- it is a vendor-neutral instrumentation standard, not an AWS
SDK, so importing it from `src/application/` doesn't violate ADR-002's "no AWS SDK
imports outside adapters" rule; if anything, it's the industry-standard version of the
same dependency-inversion goal `domain.ports` protocols exist for.

Whether a span actually goes anywhere depends entirely on whether this module's
`configure_tracing()` was called with a real OTLP collector endpoint. Unconfigured,
spans are still created (`get_tracer(...).start_as_current_span(...)` always works --
that's the OpenTelemetry API's own designed-in safe default) but are dropped immediately
by a `TracerProvider` with no span processor attached, never exported. This is the same
"provision the mechanism, a real backend is a deploy-time/operator choice" pattern
already used for the OpenAI API key secret (ADR-029) and the SNS alarm topic
subscription (Phase 6) -- this project does not deploy or assume a real OTLP collector.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_SERVICE_NAME = "aws-model-router"


def configure_tracing(otlp_endpoint: str | None = None) -> TracerProvider:
    """Configure and install the global `TracerProvider`.

    Unlike `structured_logging.configure_logging`, this is safe but *not* idempotent in
    the same "replace, don't stack" way: the OpenTelemetry API only allows the global
    provider to be set once per process (verified — a second call logs "Overriding of
    current TracerProvider is not allowed" and the original provider stays active,
    rather than raising or silently swapping). In this project that's fine as written,
    since `handlers.api_handler.handler()` only calls this once per cold start (guarded
    by the same `_SERVICES is None` check as `configure_logging()`/`build_services()`);
    it does mean tests must never rely on this global installation path — construct a
    local `TracerProvider` + `InMemorySpanExporter` directly and inject the resulting
    `Tracer` instead (see `tests/unit/application/test_tracing_instrumentation.py`).

    `otlp_endpoint` defaults to the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable.
    If neither is set, the returned provider has no span processor attached: spans are
    still created but never exported.
    """
    endpoint = (
        otlp_endpoint
        if otlp_endpoint is not None
        else os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: _SERVICE_NAME}))
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    return provider


def get_tracer() -> trace.Tracer:
    """The process-global tracer, bound to whatever `TracerProvider` is currently
    installed. Safe to call before `configure_tracing()` has run — returns a proxy that
    resolves to the real provider once one is installed (the OpenTelemetry API's own
    designed-in behavior for exactly this ordering problem).
    """
    return trace.get_tracer(_SERVICE_NAME)
