# Disaster recovery guide

Recovery procedures for a full or partial outage. See
[`deployment-and-teardown.md`](deployment-and-teardown.md) for normal deploy/destroy
operations and [`incident-response.md`](incident-response.md) for security incidents.

## What's already resilient by design

* **No single point of failure inside a Region**: API Gateway, Lambda, and DynamoDB are
  all AWS-managed, multi-AZ services within a Region — there is no EC2 instance, no
  single AZ dependency, no NAT Gateway to fail over (ADR-005).
* **Bounded, automatic model-level fallback**: a failing primary model automatically
  fails over to an approved fallback model, without any operator action (ADR-011,
  ADR-014).
* **`prod` data is retained through infrastructure changes**: `RemovalPolicy.RETAIN` on
  both DynamoDB tables means even a mistaken `cdk destroy -c env=prod` does not delete
  the decisions/idempotency tables (ADR-018).
* **Configuration is entirely reproducible from source control**: `policies/` and all
  of `infrastructure/` are version-controlled — a full environment can be rebuilt from
  git history and a `cdk deploy` alone.

## Scenario: complete stack loss (accidental full `cdk destroy`, or corrupted stack)

1. Confirm what's actually gone: `aws cloudformation describe-stacks --stack-name
   ModelRouter-<env>` (may still show `DELETE_COMPLETE` history).
2. For `prod`: the two DynamoDB tables and both CloudWatch log groups survive a stack
   deletion (`RemovalPolicy.RETAIN`) as orphaned resources — confirm they still exist
   (`aws dynamodb describe-table`) before redeploying.
3. Redeploy: `cd infrastructure && cdk deploy -c env=<env>`. This recreates the Lambda,
   API Gateway, IAM roles, dashboard, and alarms from scratch.
4. If the orphaned `prod` tables still exist, the new stack's `StorageConstruct` creates
   *new* tables with new logical IDs — it does not automatically re-adopt the orphaned
   ones. Re-associating a fresh stack with pre-existing tables requires a CDK resource
   import (`cdk import`) rather than a plain `cdk deploy` — plan and test this
   separately before relying on it in a real incident, since it is not currently
   exercised by this project's test suite.
5. Verify with `scripts/invoke_lambda_locally.py --use-real-services` against every
   route (see `deployment-and-teardown.md`).

## Scenario: Amazon Bedrock Region-wide outage/incident

1. Check the [AWS Health Dashboard](https://health.aws.amazon.com/health/status) for
   the affected Region and service.
2. If the affected models are configured with fallback to other models in the *same*
   Region, fallback alone will not help — a Region-wide Bedrock incident affects every
   model hosted there.
3. Cross-Region inference profiles are a documented, *not currently adopted*, mitigation
   for exactly this scenario — see [ADR-023](../adr/0023-cross-region-inference-profile-resilience.md)
   for the trade-offs and the IAM work required before adopting one.
4. Until/unless cross-Region profiles are adopted, the practical mitigation is
   operational: monitor `ProviderFailureAlarm`/`FallbackRateAlarm` (Phase 6) and, if the
   incident is prolonged, edit the affected application's `RoutingPolicy` to prefer a
   model catalogued in a different Region, then redeploy.

## Scenario: DynamoDB table corruption or accidental mass deletion

* **Idempotency table**: safe to lose entirely — it only ever holds transient
  in-progress/cached-result records with their own TTL; losing it just means every
  in-flight idempotency key is treated as new on the next request. No recovery action
  needed beyond redeploying if the table itself was deleted.
* **Decisions table** (`prod`): protected by point-in-time recovery
  (`enable_point_in_time_recovery=True`, ADR-018) — restore via `aws dynamodb
  restore-table-to-point-in-time` to a new table name, then update
  `DECISIONS_TABLE_NAME` (or re-point the CDK construct) to the restored table.
  `dev` has PITR disabled by design (no idle cost for disposable data) — `dev` data
  loss is expected to be acceptable; do not store anything in `dev` that isn't
  reproducible.

## Scenario: CDK deployment itself fails partway (`UPDATE_ROLLBACK_FAILED`, etc.)

1. `cdk diff -c env=<env>` to see what's actually out of sync between the last
   successful state and the current template.
2. A stack stuck in `UPDATE_ROLLBACK_FAILED` typically needs
   `aws cloudformation continue-update-rollback --stack-name ModelRouter-<env>` before
   any further `cdk deploy` will be accepted.
3. Never manually delete/recreate individual resources to "fix" a stuck stack unless
   you have confirmed exactly which resource CloudFormation considers out of sync —
   manual intervention that diverges from what CloudFormation's state expects usually
   makes the next `cdk deploy` fail differently, not succeed.

## What is explicitly not covered

Multi-Region active-active deployment, automated failover, and RTO/RPO targets are not
defined for this project — it is a single-Region-per-environment reference
architecture (ADR-005's serverless/pay-per-request scope). A production deployment with
a real availability SLA would need to define these explicitly; this guide only covers
recovering the single-Region deployment this project actually builds.
