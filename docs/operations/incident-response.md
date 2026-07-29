# Incident response guide

Procedures for responding to a suspected security incident (as opposed to an
operational alarm — see [`alarm-response.md`](alarm-response.md) for those). See
[`docs/security/threat-model.md`](../security/threat-model.md) for what's already
anticipated, and [`disaster-recovery.md`](disaster-recovery.md) for full-outage
recovery.

## Suspected cross-application data exposure (threat model T2)

If Logs Insights shows a `caller_principal_arn` that doesn't match the expected
principal for a given `application_id` (see `docs/operations/observability.md`):

```
fields @timestamp, caller_principal_arn, application_id, request_id, resource
| filter application_id = "<suspected-application>"
| stats count() by caller_principal_arn
```

1. Identify every distinct `caller_principal_arn` that has claimed the affected
   `application_id`. More than one principal claiming the same application, or a
   principal claiming multiple applications' worth of `applicationId`s it shouldn't,
   both warrant investigation.
2. Revoke or constrain the offending principal's `execute-api:Invoke` permission
   (IAM console/CLI — this is independent of any CDK-managed resource).
3. Rotate the affected application's routing policy if its cost limits/allowlists may
   have been abused (edit `policies/applications/<app>.yaml`, redeploy).
4. Consider implementing the preventive fix flagged in `threat-model.md`'s T2
   (`allowed_caller_principal_arns` on `RoutingPolicy`) if this occurs more than once.

## Suspected raw prompt/response data leak

Structured logs and audit records are designed to never carry message content
(ADR-008, ADR-019) — if one is found to contain it, that is a code defect, not
expected behavior:

1. Identify the log line/log group and the code path that produced it (the `logger`
   field names the Python logger).
2. Restrict access to the affected CloudWatch log group (`AWS Console → CloudWatch
   Logs → Actions → Edit resource policy`, or IAM) pending remediation.
3. File the defect against whichever call site passed message content through
   `extra={...}` — since `JsonFormatter` only ever includes whitelisted keys
   (`_ALLOWED_EXTRA_KEYS`), a leak means content was passed under an already-approved
   key name (e.g. embedded in `message` itself via an f-string), not that the
   whitelist was bypassed. Fix the call site, add a regression test asserting the
   specific content never appears in output (see
   `tests/unit/handlers/test_abuse_cases.py` for the pattern).
4. If genuinely sensitive data was persisted to DynamoDB (an `AuditRecord`), delete the
   specific item (`aws dynamodb delete-item`) rather than waiting for TTL expiry.

## Suspected compromised AWS credentials (Lambda execution role or deploy role)

1. Identify the specific role (`ComputeApiFunctionServiceRole...` for runtime,
   `github-actions-deploy-dev`/`-prod` for CI/CD — ADR-025) via CloudTrail.
2. Attach an explicit `Deny` policy to the affected role immediately (faster than
   waiting to redeploy with a new role) while investigating scope.
3. Rotate: for the deploy role, review/rotate the OIDC trust policy; for the Lambda
   execution role, `cdk deploy` recreates it automatically if deleted and redeployed.
4. Review CloudTrail for every API call the compromised role made during the
   suspected window before considering the incident closed.

## Suspected denial-of-wallet (cost abuse)

1. Check `ModelRouter EstimatedCostUsd` and `RequestCount` (Phase 6 dashboard) for the
   affected period — is this concentrated in one `application_id`?
2. Cross-check AWS Cost Explorer for actual billed Bedrock spend — the router's
   estimate is guidance, not authoritative (`docs/cost/cost-estimation-guide.md`).
3. Tighten the affected application's `RoutingPolicy.maximum_estimated_cost_usd` and/or
   `maximum_output_tokens`, redeploy.
4. If the traffic pattern suggests credential compromise rather than legitimate
   overuse, follow the credential-compromise procedure above instead.

## After any incident

Update `docs/security/threat-model.md` if the incident reveals a threat not already
enumerated, or changes the status/residual-risk assessment of an existing one — the
threat model is a living document, not a one-time artifact.
