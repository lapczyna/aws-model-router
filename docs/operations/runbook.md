# Operational runbook

Routine tasks for operating a deployed `aws-model-router` stack. For alarm-specific
guidance see [`alarm-response.md`](alarm-response.md); for logs/metrics reference see
[`observability.md`](observability.md); for deploy/teardown see
[`deployment-and-teardown.md`](deployment-and-teardown.md).

## Health checks

```bash
curl https://<ApiUrl>/health   # {"status": "ok"} — process liveness, no dependencies
curl https://<ApiUrl>/ready    # {"status": "ready", "modelCatalogueVersion": N}
```

Both are unauthenticated (ADR-015). `/ready` reaching a response at all means the
bundled model catalogue loaded successfully at cold start — there is no separate
`"not_ready"` response (`docs/architecture/api-contracts.md`).

## Checking recent activity for an application

```
fields @timestamp, message, status_code, capability, error_code
| filter application_id = "<applicationId>"
| sort @timestamp desc
| limit 100
```

## Looking up a specific routing decision

```bash
curl -H "Authorization: <SigV4>" \
  "https://<ApiUrl>/v1/decisions/<decisionId>?applicationId=<applicationId>"
```

Returns `404` if the decision doesn't exist or has passed its retention window
(`EnvironmentConfig.decisions_retention_seconds`); `403` if `applicationId` doesn't
match the decision's owner (ADR-015's caller/`applicationId` binding limitation applies
here too — the caller must supply the correct `applicationId` themselves).

## Updating routing policy or the model catalogue

Both are version-controlled YAML under `policies/`, bundled directly into the Lambda
deployment package (ADR-010's "Phase 5+" DynamoDB/SSM-backed config store was
deliberately not built — see `PROJECT_PLAN.md`'s Open Assumptions). Changing either
requires a code change and redeploy:

```bash
# edit policies/model_catalogue.yaml or policies/applications/<app>.yaml
cd infrastructure && cdk deploy -c env=<env>
```

There is no live/hot-reload path — a policy change never takes effect without a
redeploy.

## Rotating/raising Lambda concurrency or memory

Edit `infrastructure/config.py`'s `EnvironmentConfig` for the target environment
(`lambda_reserved_concurrency`, `lambda_memory_mb`), then `cdk deploy`. These are not
runtime-configurable — there is no console toggle that survives the next deploy.

## Adjusting alarm thresholds

Edit the relevant `*_alarm_threshold*` field in `infrastructure/config.py`'s
`EnvironmentConfig`, then `cdk deploy -c env=<env>`. Thresholds are code, not console
state — a manual console edit to an alarm is silently overwritten by the next deploy.

## Subscribing to alarm notifications

No subscription exists until you create one (ADR-021 — no email/Slack endpoint was
fabricated on your behalf):

```bash
aws sns subscribe --topic-arn <AlarmTopicArn> --protocol email --notification-endpoint you@example.com
```

## Investigating a spike in fallback or provider failures

See [`alarm-response.md`](alarm-response.md#providerfailurealarm) and
[`alarm-response.md`](alarm-response.md#fallbackratealarm) — the short version: check
`ModelRouter ProviderFailureCount` broken down by `ModelAlias`/`Status` via Logs
Insights before assuming a systemic issue.
