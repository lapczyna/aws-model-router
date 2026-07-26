# ADR-004: AWS CDK with Python

## Status
Accepted

## Context
The project provisions multiple integrated serverless resources (API Gateway, Lambda,
DynamoDB, CloudWatch alarms/dashboards, IAM roles) across separate development and
production environments. The infrastructure needs to be typed, testable, reusable across
environments, and maintainable by the same team writing the application code (Python).

## Decision
Infrastructure is defined using AWS CDK v2 in Python. Terraform and AWS SAM are not used
unless a concrete CDK limitation is encountered and documented (see the exception below).

## Consequences
* Infrastructure and application code share a single language, type system, and toolchain
  (mypy, pytest), lowering the cost of context-switching and enabling infrastructure unit
  tests (CDK assertions) alongside application unit tests.
* CDK constructs allow reusable, parameterized environment stacks (dev/prod) instead of
  duplicated templates.
* For Bedrock resources without stable high-level ("L2") CDK constructs, the project uses
  stable CloudFormation-level ("L1", `Cfn*`) constructs, or passes existing resource
  identifiers through configuration/context — not experimental CDK modules — to avoid
  taking on unreviewed stability risk. Any exception to this is documented inline in the
  relevant stack and cross-referenced from this ADR when it happens.
* CDK's synthesis step (CloudFormation) is a real, if indirect, dependency; template size
  and IAM policy generation must be reviewed as part of infrastructure changes (Phase 5
  CDK tests cover this).

## Alternatives considered
* **Terraform** — rejected: would require a second language/toolchain and a separate
  state-management story (remote state, locking) for a single-team, single-account
  reference project where CDK's CloudFormation-native state management is sufficient.
* **AWS SAM** — rejected: narrower in scope than CDK for cross-resource composition
  (DynamoDB, alarms, dashboards, IAM policies beyond a single function), and CDK can
  express everything SAM does via the Lambda/API Gateway L2 constructs plus more.
* **Raw CloudFormation/YAML** — rejected: no type safety, no reusable constructs, and
  significantly more boilerplate for parameterizing dev vs. prod.
