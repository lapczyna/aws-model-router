# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for `aws-model-router`.
An ADR captures a significant, hard-to-reverse decision: the context that forced it, the
decision itself, and the consequences (including what was given up).

## When to add an ADR

Add one when a change:

* introduces a new architectural direction (a new layer, a new external dependency, a new
  storage system),
* closes a previously open question,
* reverses or supersedes an earlier decision, or
* establishes a policy that future contributors would otherwise have to rediscover by
  reading code (e.g. why fallback doesn't happen for a category of failure).

Small, easily-reversible implementation choices do not need an ADR — use a code comment
or PR description instead.

## Format

```markdown
# ADR-XXX: <Title>

## Status
Accepted | Proposed | Superseded by ADR-YYY

## Context
What forces are at play? What constraint or problem made a decision necessary?

## Decision
What was decided, stated as a clear, active sentence.

## Consequences
What becomes easier or harder as a result? What did we give up?

## Alternatives considered
What else was evaluated, and why was it not chosen?
```

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](0001-centralized-model-routing.md) | Centralized model routing | Accepted |
| [ADR-002](0002-provider-independent-domain-architecture.md) | Provider-independent domain architecture | Accepted |
| [ADR-003](0003-amazon-bedrock-as-initial-provider.md) | Amazon Bedrock as initial provider | Accepted |
| [ADR-004](0004-aws-cdk-with-python.md) | AWS CDK with Python | Accepted |
| [ADR-005](0005-serverless-pay-per-request-architecture.md) | Serverless, pay-per-request architecture | Accepted |
| [ADR-006](0006-model-aliases-instead-of-client-supplied-model-ids.md) | Model aliases instead of client-supplied model IDs | Accepted |
| [ADR-007](0007-deterministic-explainable-routing.md) | Deterministic, explainable routing | Accepted |
| [ADR-008](0008-metadata-only-audit-records-by-default.md) | Metadata-only audit records by default | Accepted |
| [ADR-009](0009-converse-api-as-normalized-bedrock-interface.md) | Converse API as the normalized Bedrock interface | Accepted |
| [ADR-010](0010-configuration-storage-approach.md) | Configuration storage approach | Accepted |
| [ADR-011](0011-fallback-eligibility.md) | Fallback eligibility | Accepted |
| [ADR-012](0012-deterministic-experimentation.md) | Deterministic experimentation | Accepted |
| [ADR-013](0013-idempotency-strategy.md) | Idempotency strategy | Accepted |
| [ADR-014](0014-retry-and-cost-amplification-controls.md) | Retry and cost-amplification controls | Accepted |
| [ADR-015](0015-api-authorization-model.md) | API authorization model | Accepted |
| [ADR-016](0016-single-shared-lambda-handler.md) | Single shared Lambda handler | Accepted |
| [ADR-017](0017-lambda-packaging-without-experimental-cdk-constructs.md) | Lambda packaging without experimental CDK constructs | Accepted |
| [ADR-018](0018-dynamodb-decision-and-idempotency-store-design.md) | DynamoDB decision and idempotency store design | Accepted |
| [ADR-019](0019-observability-approach.md) | Observability approach — structured logging and EMF custom metrics | Accepted |
| [ADR-020](0020-model-health-signal-scope.md) | Model health signal — scope and derivation | Accepted |
| [ADR-021](0021-alerting-design.md) | Alerting design — CloudWatch alarms and a single SNS topic | Accepted |
| [ADR-022](0022-least-privilege-iam-review.md) | Least-privilege IAM review | Accepted |
| [ADR-023](0023-cross-region-inference-profile-resilience.md) | Cross-Region inference profile resilience evaluation | Accepted |
| [ADR-024](0024-responsible-ai-gateway-placement.md) | Responsible AI Gateway placement | Accepted |
| [ADR-025](0025-github-oidc-deploy-role-design.md) | GitHub OIDC deploy role design | Accepted |
| [ADR-026](0026-pr-and-deploy-workflow-separation.md) | PR and deployment workflow separation | Accepted |
| [ADR-027](0027-iac-security-scanning-approach.md) | IaC security scanning — cdk-nag and cfn-lint | Accepted |
| [ADR-028](0028-fallback-chain-considers-health-excluded-candidates.md) | Fallback chain must apply even when the strategy selects nothing | Accepted |
| [ADR-029](0029-multi-provider-routing-openai.md) | Multi-provider routing — OpenAI as the second provider | Accepted |
