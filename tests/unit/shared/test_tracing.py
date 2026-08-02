"""Tests `shared.tracing.configure_tracing` — verifies the two observable outcomes that
actually matter: spans can always be created without error (whether or not export is
configured), and a configured OTLP endpoint results in a real span processor being
attached (so it would actually export somewhere, not just silently no-op).

Every test here patches out `trace.set_tracer_provider` so `configure_tracing()`'s
side effect never actually installs a provider as the process-global one. This matters:
OpenTelemetry only allows the global provider to be set *once* per process (verified —
a second call is silently ignored, not replaced), so if a real test here were allowed to
win that race, every *other* test in the suite that uses the default tracer (i.e. never
explicitly injects one) would silently start emitting real spans against whatever
endpoint this file's tests happened to configure — observed directly during development
as background `BatchSpanProcessor` export-retry noise bleeding into unrelated test
output. Testing `configure_tracing()`'s own logic only needs its *return value*, never
the global installation.
"""

import pytest

from shared.tracing import configure_tracing

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _never_install_globally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.tracing.trace.set_tracer_provider", lambda provider: None)


def test_configure_tracing_without_endpoint_attaches_no_span_processor() -> None:
    provider = configure_tracing(otlp_endpoint=None)

    assert provider._active_span_processor._span_processors == ()

    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("foo", "bar")  # must not raise


def test_configure_tracing_with_endpoint_attaches_a_span_processor() -> None:
    # Deliberately never creates a span against this provider: span creation would
    # queue work for the BatchSpanProcessor's background export thread, which would
    # then have to actually attempt (and retry, with backoff) a connection to this
    # unreachable local endpoint before the process exits — slow and noisy for a unit
    # test that only needs to verify a processor was attached, not that export works.
    provider = configure_tracing(otlp_endpoint="http://localhost:4318/v1/traces")

    processors = provider._active_span_processor._span_processors
    assert len(processors) == 1


def test_configure_tracing_reads_otel_exporter_otlp_endpoint_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")

    provider = configure_tracing()

    assert len(provider._active_span_processor._span_processors) == 1


def test_configure_tracing_explicit_empty_endpoint_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit (even empty) `otlp_endpoint` argument takes precedence over the
    environment variable — only an omitted/`None` argument falls back to it."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")

    provider = configure_tracing(otlp_endpoint="")

    assert provider._active_span_processor._span_processors == ()
