# Operations documentation

Operational runbooks and alarm-response guides.

* [`deployment-and-teardown.md`](deployment-and-teardown.md) — deploying `dev`/`prod`
  with CDK, verifying a deployment, and what `RemovalPolicy.RETAIN` actually means for
  `cdk destroy -c env=prod` (Phase 5).
* [`observability.md`](observability.md) — the structured log schema, the custom metric
  set and why every metric declares only one CloudWatch dimension, and how to read the
  CloudWatch dashboard (Phase 6).
* [`alarm-response.md`](alarm-response.md) — what each of the seven alarms means and
  what to check first when one fires (Phase 6).
* [`runbook.md`](runbook.md) — routine operational tasks: health checks, looking up a
  decision, updating policy/catalogue, adjusting Lambda/alarm configuration, subscribing
  to alarm notifications (Phase 6).
* [`incident-response.md`](incident-response.md) — responding to a suspected security
  incident (cross-application data exposure, data leakage, credential compromise,
  cost abuse) — see `docs/security/threat-model.md` for what's anticipated (Phase 7).
* [`disaster-recovery.md`](disaster-recovery.md) — recovering from full stack loss, a
  Region-wide Bedrock incident, DynamoDB data loss, or a stuck CDK deployment (Phase 7).
