# Operations documentation

Operational runbooks and alarm-response guides.

* [`deployment-and-teardown.md`](deployment-and-teardown.md) — deploying `dev`/`prod`
  with CDK, verifying a deployment, and what `RemovalPolicy.RETAIN` actually means for
  `cdk destroy -c env=prod` (Phase 5).

Alarm-response and incident/disaster-recovery guides are populated in Phase 6
(observability/dashboards/alarms) and Phase 7, once there is a deployed system with live
telemetry to operate against.
