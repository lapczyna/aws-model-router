# ADR-019: Observability approach — structured logging and EMF custom metrics

## Status
Accepted

## Context
Phase 6 requires structured, safe-attribute-only JSON logs (`docs/requirements.md`
NFR-4.1) and a custom metrics set with low-cardinality dimensions only (NFR-4.2: never
`requestId`/`decisionId`/`conversationId`/an end-user identifier as a metric dimension).
Two mechanisms were available for the custom metrics: a direct `cloudwatch:PutMetricData`
boto3 call from the Lambda, or the CloudWatch Embedded Metric Format (EMF) — a
specially-shaped JSON log line that CloudWatch Logs auto-extracts into real metrics.

## Decision
**Logging**: `src/shared/structured_logging.py` configures the root logger with a
`JsonFormatter` emitting one JSON object per record (`timestamp`, `level`, `logger`,
`message`, plus any allow-listed `extra` field). `_ALLOWED_EXTRA_KEYS` is a fixed,
explicit set (`request_id`, `decision_id`, `application_id`, `capability`, `model_alias`,
`provider`, `error_code`, `latency_ms`, `status_code`, `http_method`, `resource`) — any
`extra` key not on this list is silently dropped, not raised, so a future call site
adding a field it forgot to whitelist loses that one field rather than breaking the
request. Raw prompt/response content is never logged (unchanged from ADR-008 — nothing
in this whitelist could carry it).

**Metrics**: `src/adapters/metrics/emf_metrics_publisher.py`'s `EmfMetricsPublisher`
writes one EMF-formatted JSON line (via `print()`) per metric point — no
`PutMetricData` call, no extra IAM permission beyond the `logs:PutLogEvents` every
Lambda already has via its execution role. `InvocationOrchestrator` calls
`MetricsPublisher.publish(result)` once per completed `POST /v1/inference` call, passing
the whole `InferenceResult` rather than exploded fields, so the publisher — not every
caller — decides what to derive from it (mirrors `RoutingDecisionRepository.save`).

**Dimension design**: every metric declares exactly one CloudWatch dimension —
`Environment` — never `Capability`/`ModelAlias`/`Status`/`ApplicationId`, even though
those ride along in the same JSON line as plain (non-dimension) properties. A CloudWatch
metric's identity is its namespace + metric name + *exact* dimension set; dimensioning
by e.g. `ModelAlias` would fragment `ProviderFailureCount` into one untraceable time
series per model, which a CDK-defined alarm (fixed at synth time) could never reliably
reference without hardcoding every model alias from the catalogue into the CDK stack.
One stable, always-present `{Environment}`-dimensioned series per metric name is what
`cdk_constructs/observability_construct.py`'s alarms are built against. Per-model/
per-capability breakdowns remain fully available via CloudWatch Logs Insights queries
over the same structured log lines (`docs/operations/observability.md`).

`EmfMetricsPublisher._put_metric` enforces `_ALLOWED_EXTRA_KEYS` the same way the logger
enforces its whitelist — but by raising `ValueError`, not silently dropping — since a
disallowed property here would be a metrics-code defect (a wrong hardcoded key), not
routine caller variance, and a loud unit-test failure is preferable to a metric that
silently doesn't record what an alarm depends on. See
`tests/unit/adapters/metrics/test_emf_metrics_publisher.py`.

## Consequences
* Zero new IAM permissions for either logs or metrics — the entire observability surface
  rides on the log group access every Lambda already has.
* One EMF JSON line per metric point (not batched) — simpler and more obviously correct
  than hand-rolled batching, at the cost of more log lines than a batched approach; an
  acceptable trade-off at this project's traffic scale, revisit if log volume/cost
  becomes material.
* Per-model/per-capability metric breakdowns require a Logs Insights query, not a
  dashboard widget with a `ModelAlias` dimension selector — a deliberate simplicity/
  robustness trade-off over per-entity dashboarding.
* `configure_logging()` is only called from `handler()` (the real Lambda entry point),
  never at module import time — importing `api_handler` in a unit test never mutates the
  root logger's handlers process-wide.

## Alternatives considered
* **Direct `cloudwatch:PutMetricData` calls** — rejected: costs a real API call (latency
  + a small per-request charge) per metric point, requires an additional IAM permission,
  and offers no advantage over EMF for this project's metric volume.
* **Dimensioning metrics by `ModelAlias`/`Capability` directly** — rejected: as above,
  fragments each metric into a number of time series unknown at CDK-synth time, making
  static alarm definitions impossible without hardcoding catalogue contents into
  infrastructure code (a config/infra coupling this project otherwise avoids — ADR-010).
* **A logging library (`structlog`, `python-json-logger`)** — rejected: `JsonFormatter`
  is ~30 lines against the stdlib `logging` module already used throughout; a dependency
  buys little at this scope and keeps the Lambda's bundled dependency set (ADR-017)
  minimal.
