# ADR-021: Alerting design — CloudWatch alarms and a single SNS topic

## Status
Accepted

## Context
Phase 6 requires a CloudWatch dashboard and alarms for: Lambda errors, API 5xx, provider
failure, fallback rate, no-eligible-model, throttling, and estimated-spend guidance
(`PROJECT_PLAN.md`). Alarms need an action to be operationally meaningful, but no real
notification endpoint (email, Slack, PagerDuty) was ever specified — fabricating one
would either be a fake, non-functional placeholder or a real contact address invented
without authorization.

## Decision
`cdk_constructs/observability_construct.py` provisions one SNS topic
(`model-router-{env}-alarms`, `enforce_ssl=True`) per environment and attaches it as the
action for every alarm. **No subscription is created by CDK.** The topic ARN is a stack
output (`AlarmTopicArn`); `docs/operations/deployment-and-teardown.md` and
`docs/operations/alarm-response.md` document subscribing a real endpoint post-deploy
(`aws sns subscribe --topic-arn <arn> --protocol email --notification-endpoint you@example.com`,
or a Slack/chatbot integration).

Seven alarms, each evaluated over a 5-minute period (3 consecutive breaching periods
required, except the daily spend alarm — see below) with
`comparison_operator=GREATER_THAN_OR_EQUAL_TO_THRESHOLD`:

| Alarm | Metric | Source |
|---|---|---|
| `LambdaErrorsAlarm` | `AWS/Lambda Errors` | Native (`function.metric_errors()`) |
| `LambdaThrottlesAlarm` | `AWS/Lambda Throttles` | Native (`function.metric_throttles()`) |
| `Api5xxAlarm` | `AWS/ApiGateway 5XXError` | Native (`rest_api.metric_server_error()`) |
| `ProviderFailureAlarm` | `ModelRouter ProviderFailureCount` | Custom (EMF, ADR-019) |
| `FallbackRateAlarm` | `(FallbackUsedCount / RequestCount) * 100` | Custom, `MathExpression` |
| `NoEligibleModelAlarm` | `ModelRouter NoEligibleModelCount` | Custom (EMF) |
| `EstimatedDailySpendAlarm` | `ModelRouter EstimatedCostUsd`, 1-day period | Custom (EMF), 1 evaluation period |

"Throttling" is Lambda-level (`metric_throttles` — reserved/account concurrency
exhausted), not an API Gateway usage-plan metric: API Gateway REST APIs do not publish a
dedicated throttle-count metric analogous to Lambda's, whereas Lambda throttling ties
directly to `EnvironmentConfig.lambda_reserved_concurrency`, an existing, meaningful
per-environment knob (ADR from Phase 5's `config.py`). Every threshold is
`EnvironmentConfig`-driven (dev looser, prod tighter) — see `infrastructure/config.py`.

`FallbackRateAlarm` and `EstimatedDailySpendAlarm` use
`treat_missing_data=NOT_BREACHING`: a fallback rate with zero traffic (undefined ratio,
missing datapoints) or a day with no invocations at all must never be treated as an
alarm condition.

## Consequences
* No IAM change to the Lambda's execution role — CloudWatch alarms invoke SNS via
  CloudWatch's own service permissions, not the monitored Lambda's role.
* An operator must explicitly subscribe an endpoint after `cdk deploy` before alarms
  produce any human-visible notification — documented, not silent; the alarms
  themselves (visible in the CloudWatch console/API and exercised by
  `tests/infra/test_observability_construct.py`) exist and evaluate regardless.
* `EstimatedDailySpendAlarm` is explicitly "guidance" (ADR-019: estimated cost is never
  billed cost) — its alarm description says so, so an on-call responder never mistakes
  it for an AWS Budgets/billing alarm.
* Adding a real notification channel later (e.g. a Slack chatbot integration) is an
  `sns.Subscription` addition to the existing topic, not an alarm redesign — not built
  in Phase 7 either, for the same reason it wasn't built here (no real endpoint to
  target).

## Alternatives considered
* **AWS Chatbot / Slack integration built in now** — rejected: requires a real,
  authorized Slack workspace/channel to target, which this project does not have;
  revisit if/when one is provided.
* **A hardcoded placeholder email subscription** — rejected: a fake address is either
  non-functional (bounces silently) or, worse, a real address chosen without the user's
  knowledge — neither is acceptable.
* **CloudWatch anomaly detection alarms** instead of static thresholds — rejected for
  this phase: anomaly detection needs weeks of real traffic history to calibrate
  meaningfully; static, `EnvironmentConfig`-driven thresholds are simpler, immediately
  effective, and adjustable without redeploying detection models.
