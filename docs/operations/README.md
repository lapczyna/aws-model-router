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

Incident-response and disaster-recovery guides are populated in Phase 7, once the
security/resilience hardening phase defines the threat model they respond to.
