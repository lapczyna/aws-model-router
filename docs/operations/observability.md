# Observability guide

What the router logs, what metrics it publishes, and how to read the CloudWatch
dashboard (`cdk_constructs/observability_construct.py`, ADR-019). See
[`alarm-response.md`](alarm-response.md) for what to do when one of the alarms fires,
and [`runbook.md`](runbook.md) for day-to-day operational tasks.

## Structured logs

Every log line the Lambda emits is one JSON object
(`src/shared/structured_logging.py:JsonFormatter`), with these fields:

| Field | Always present? | Meaning |
|---|---|---|
| `timestamp` | Yes | ISO 8601 UTC |
| `level` | Yes | `INFO`, `WARNING`, `ERROR`, etc. |
| `logger` | Yes | The Python logger name |
| `message` | Yes | Human-readable message (never raw prompt/response content — ADR-008) |
| `exception` | Only on `logger.exception(...)` | Formatted traceback |
| `request_id` | Most request-handling logs | API Gateway's request ID |
| `decision_id` | When a decision exists | The routing decision ID |
| `application_id` | Most request-handling logs | The calling application |
| `capability` | Most request-handling logs | The requested capability |
| `model_alias` | Attempt-level logs | Which model was involved |
| `provider` | Attempt-level logs | e.g. `bedrock` |
| `error_code` | Error logs | The `ErrorResponse.errorCode` returned to the caller |
| `latency_ms` | Attempt-level logs | Invocation latency |
| `status_code` | Every completed request | HTTP status returned |
| `http_method` / `resource` | Every completed request | Which route was called |
| `caller_principal_arn` | Every completed request | The authenticated IAM principal's ARN (`"none"` for `/health`/`/ready`) — a detective control for `applicationId` spoofing (threat model T2, ADR-015): correlate this against the request's claimed `applicationId` if abuse is suspected |

This is the **complete, fixed list** (`_ALLOWED_EXTRA_KEYS` in
`structured_logging.py`) — any `extra={...}` key not on it is silently dropped by the
formatter, not raised, so a call site that passes an unlisted field loses that one field
rather than crashing the request. Extending the list is a deliberate code change, not
something a caller can do by just passing a new keyword.

Query logs directly with **CloudWatch Logs Insights** against the Lambda's log group,
e.g. every error for a given application in the last day:

```
fields @timestamp, message, error_code, status_code
| filter application_id = "support-assistant" and level = "ERROR"
| sort @timestamp desc
```

## Metrics

Namespace: **`ModelRouter`**. Every custom metric declares exactly one CloudWatch
dimension — `Environment` (`dev`/`prod`) — never `Capability`/`ModelAlias`/`Status`/
`ApplicationId`, even though those ride along as plain (non-dimension) properties in the
same EMF log line (ADR-019 explains why: per-model/per-capability dimensioning would
fragment each metric into untraceable time series a CDK-defined alarm couldn't reliably
target). Use Logs Insights, not the metric dimension picker, for that breakdown:

```
fields @timestamp, ModelAlias, Status, InvocationLatencyMs
| filter ispresent(InvocationAttemptCount)
| stats avg(InvocationLatencyMs), count() by ModelAlias, Status
```

| Metric | Unit | Emitted when |
|---|---|---|
| `RequestCount` | Count | Every completed `POST /v1/inference` call |
| `FallbackUsedCount` | Count (0 or 1) | Every completed call — `1` if fallback was used |
| `NoEligibleModelCount` | Count (0 or 1) | Every completed call — `1` if no model was eligible |
| `EstimatedCostUsd` | None | Only when a model was actually invoked (has `ApplicationId`) |
| `InvocationAttemptCount` | Count | Once per invocation attempt (has `ModelAlias`, `Status`) |
| `InvocationLatencyMs` | Milliseconds | Once per invocation attempt |
| `ProviderFailureCount` | Count | Once per non-`succeeded` invocation attempt |

Native AWS metrics used directly (no application code): `AWS/Lambda` `Errors` /
`Throttles` / `Duration`; `AWS/ApiGateway` `5XXError` / `4XXError` / `Count` / `Latency`.

**Estimated cost is never billed cost** (ADR-005) — `EstimatedCostUsd` is derived from
the router's own pricing configuration (`policies/model_catalogue.yaml`), useful as a
trend/guidance signal, not a substitute for AWS Cost Explorer/Budgets. See
[`docs/cost/cost-estimation-guide.md`](../cost/cost-estimation-guide.md).

## Dashboard

`cdk deploy` outputs a `DashboardUrl` pointing at `model-router-{env}`, with three rows:
Lambda health (errors/throttles) and API 5xx; request volume/fallback/no-eligible-model
and the fallback-rate math expression; provider failures and estimated daily cost.

## Why EMF instead of `PutMetricData`

Every metric point is one CloudWatch Embedded Metric Format JSON line written via
`print()` — captured by the Lambda's existing log group and auto-extracted into real
metrics by CloudWatch, with no extra `PutMetricData` API call and no new IAM permission.
See ADR-019 for the full rationale, including the one-line-per-metric-point trade-off
(simpler and more obviously correct than hand-rolled batching, at the cost of more log
lines than a batched approach).
