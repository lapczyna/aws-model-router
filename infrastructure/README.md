# Infrastructure

AWS CDK v2 (Python) application defining all deployable resources: API Gateway REST API,
Lambda functions, DynamoDB tables, CloudWatch log groups/alarms/dashboards, and IAM
roles.

Not yet implemented — this is Phase 5 scope (see
[`PROJECT_PLAN.md`](../PROJECT_PLAN.md)). No AWS infrastructure exists in this repository
before that phase. `app.py`, `cdk.json`, `stacks/`, `constructs/`, and `tests/` land here
then.

Architectural decisions already made that will shape this directory:

* [ADR-004](../docs/adr/0004-aws-cdk-with-python.md) — AWS CDK with Python
* [ADR-005](../docs/adr/0005-serverless-pay-per-request-architecture.md) — serverless,
  pay-per-request only (no EC2/ECS/EKS, no NAT Gateway, no provisioned Bedrock throughput)
