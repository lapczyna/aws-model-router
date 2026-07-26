# ADR-007: Deterministic, explainable routing

## Status
Accepted

## Context
A routing decision affects both cost and behavior for the calling application. If
routing were opaque (e.g. a learned/black-box model choosing routes), it would be
difficult to audit, debug, reproduce, or explain to a caller why a particular model was
used — and difficult to trust in a cost- and governance-sensitive system.

## Decision
All routing strategies in the base implementation are deterministic and produce an
explanation as a set of stable `RoutingReasonCode`s (see
`docs/architecture/domain-glossary.md#reason-codes`). Given the same request, resolved
policy, model catalogue, and health snapshot, the router always produces the same
decision. Weighted experimentation (Phase 4) uses deterministic hashing of a stable
subject key rather than randomization, so repeated calls for the same subject land in the
same cohort. Opaque, machine-learning-based routing is explicitly out of scope for the
base project.

## Consequences
* Every decision can be explained via `POST /v1/routes/evaluate` and
  `GET /v1/decisions/{decisionId}` without invoking a model, which is valuable for
  debugging, cost review, and demonstrating governance to stakeholders.
* Tests can assert exact, repeatable routing outcomes (Phase 2), rather than statistical
  behavior.
* The router cannot adapt routing quality based on feedback signals it hasn't been
  explicitly configured to consider (e.g. no learned quality scoring) — any future
  adaptive/learning-based strategy is required to run in shadow mode first and never
  control production traffic without separate validation (see `PROJECT_PLAN.md`,
  Phase 10).
* Reason codes become a versioned, semi-public contract: they must not be renamed or
  repurposed once introduced, only added to.

## Alternatives considered
* **Learned/bandit-based routing from the start** — rejected for the base project:
  harder to test deterministically, harder to explain to a caller or auditor, and risks
  optimizing for an implicit signal (e.g. latency) at the expense of an explicit policy
  (e.g. cost ceiling) without visibility. Considered only as a future, shadow-mode
  extension (Phase 10).
* **Random load-balancing across eligible candidates** — rejected: not reproducible, not
  explainable, and not desirable for experiment cohorts, which specifically need stable,
  repeatable assignment per subject.
