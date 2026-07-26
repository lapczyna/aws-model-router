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

Future ADRs (fallback eligibility, deterministic experimentation, idempotency strategy,
retry/cost amplification controls, API authorization model, cross-Region resilience,
Responsible AI Gateway placement) are added in the phases where those decisions are made
(Phases 4, 5, and 7 respectively — see `PROJECT_PLAN.md`).
