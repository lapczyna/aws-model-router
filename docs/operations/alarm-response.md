# Alarm response guide

What each alarm (`cdk_constructs/observability_construct.py`, ADR-021) means and what to
check first. All seven notify the same SNS topic (`AlarmTopicArn` stack output) — no
subscription is created by CDK; subscribe your own endpoint post-deploy:

```bash
aws sns subscribe --topic-arn <AlarmTopicArn> --protocol email --notification-endpoint you@example.com
```

See [`observability.md`](observability.md) for the underlying metrics/logs and
[`runbook.md`](runbook.md) for routine operational tasks.

---

### `LambdaErrorsAlarm`
**Meaning**: the API Lambda function is raising unhandled exceptions (`AWS/Lambda`
`Errors`). Every `dispatch()` call already catches its own exceptions into a `500
INTERNAL_ERROR` response (`src/handlers/api_handler.py`), so this specifically means an
exception escaped *even that* — a defect in the handler's own error-handling path, or an
error during Lambda init (cold start) before `dispatch()` ever runs.

**First checks**: CloudWatch Logs Insights for `level = "ERROR"` in the same window (the
`exception` field has the traceback); confirm `/ready` still returns `200` (cold-start
config-load failures fail every subsequent invocation until a new execution
environment starts).

### `LambdaThrottlesAlarm`
**Meaning**: the function is being throttled (`AWS/Lambda` `Throttles`) — reserved
concurrency (`EnvironmentConfig.lambda_reserved_concurrency`) or the account-wide
concurrency limit was exhausted.

**First checks**: is this a genuine traffic spike (check `RequestCount`) or a
concurrency leak (a caller retrying aggressively against a failing dependency)? Raising
`lambda_reserved_concurrency` in `infrastructure/config.py` is a redeploy; it is not an
emergency runtime lever.

### `Api5xxAlarm`
**Meaning**: API Gateway itself is returning 5xx (`AWS/ApiGateway` `5XXError`) — either
the integration (Lambda) failed outright, or API Gateway couldn't reach it.

**First checks**: correlate with `LambdaErrorsAlarm`/`LambdaThrottlesAlarm` in the same
window — a 5xx spike with no corresponding Lambda alarm suggests an API Gateway-side or
IAM-authorization-configuration issue rather than application code.

### `ProviderFailureAlarm`
**Meaning**: model invocations are failing at a sustained rate (`ModelRouter
ProviderFailureCount` — throttled/transient/timeout attempts, from
`EmfMetricsPublisher`). This is expected to correlate with fallback activity
(`FallbackRateAlarm`) if fallback is configured for the affected application(s).

**First checks**: Logs Insights `stats count() by ModelAlias, Status` (see
`observability.md`) to identify which model/failure category dominates. A sustained
`throttled` rate against one model may indicate its Bedrock quota needs raising; a
`timeout` spike may indicate a Bedrock-side incident (check the AWS Health Dashboard).

### `FallbackRateAlarm`
**Meaning**: a high proportion of requests are being served by a non-primary model
(`(FallbackUsedCount / RequestCount) * 100`). `treat_missing_data=NOT_BREACHING` — zero
traffic never trips this.

**First checks**: this is a *consequence* of `ProviderFailureAlarm` in the same
window, not an independent root cause — investigate that alarm's guidance first. A high
fallback rate with no corresponding provider-failure signal may indicate a policy
misconfiguration routing more traffic than intended to a fallback tier.

### `NoEligibleModelAlarm`
**Meaning**: a sustained rate of requests find no eligible model
(`ModelRouter NoEligibleModelCount`) — every candidate was filtered out (capability not
permitted, cost limit, token limit, model health) or the requested capability isn't in
the catalogue at all.

**First checks**: Logs Insights for `errorCode = "REQUIRED_CAPABILITY_UNAVAILABLE"` or
`"NO_ELIGIBLE_MODEL"` in the same window (`docs/architecture/api-contracts.md`'s error
table) — this usually points to a specific application's policy or a recent catalogue
change, not a systemic failure.

### `EstimatedDailySpendAlarm`
**Meaning — advisory only** (ADR-019: estimated cost is never billed cost). Daily
estimated Bedrock spend (`ModelRouter EstimatedCostUsd`, summed over a 1-day period) is
trending above the configured threshold (`EnvironmentConfig.estimated_daily_spend_alarm_threshold_usd`).

**First checks**: this is guidance, not a billing alert — cross-check AWS Cost
Explorer/Budgets for the actual billed amount before treating it as urgent. If
consistently over budget, review per-application cost limits
(`RoutingPolicy.maximum_estimated_cost_usd`) and the model catalogue's pricing/tier mix.
