# ADR-012: Deterministic experimentation

## Status
Accepted

## Context
The router needs to support A/B-style routing experiments (e.g. "send 30% of
`support-assistant` traffic to a new model") without introducing non-determinism into an
otherwise fully explainable, reproducible routing engine (ADR-007). A naive
random-per-request assignment would put the same conversation in different cohorts on
every turn, making the experiment's results meaningless and the router's behavior
unreproducible for a given input.

## Decision
Experiment routing is implemented as `domain.experiment.ExperimentStrategy`, a fourth
`RoutingStrategy` (alongside preferred-model, lowest-cost, and quality-tier from
Phase 2), selected via `RoutingPolicy.routing_strategy = "experiment"` and configured
with `RoutingPolicy.experiment_policy`.

Cohort assignment is a pure function of a *stable subject key*: `experiment_id` combined
with the application ID and/or conversation ID (`ExperimentPolicy.subject_key_source`),
hashed with SHA-256 into `[0, 1)` and mapped to an arm proportional to its configured
weight (`domain.experiment.assign_experiment_cohort`). There is no randomness and no
external state — the same subject key always produces the same arm, for as long as the
experiment's arm configuration is unchanged, and the `experiment_id` is always the first
component of the subject key, so two concurrent experiments over the same
application/conversation are assigned independently rather than correlated.

If the arm assigned by cohort hashing is not in the eligible candidate set for this
specific request (e.g. it fails a cost or token check), `ExperimentStrategy` does **not**
reassign to a different arm — it returns no selection, the same as any other strategy
whose target is ineligible. Silently reassigning would bias the experiment's population
(only requests where the assigned arm happens to be affordable would ever run) and
contaminate its statistical validity.

## Consequences
* Repeated evaluation of the same request is fully deterministic and testable without
  mocking any random number generator.
* Running multiple experiments simultaneously is safe — they cannot correlate or bias
  each other, because each hashes independently, seeded by its own `experiment_id`.
* An experiment arm can still be excluded by ordinary eligibility rules (cost, tokens,
  allowlist) — an experiment cannot be used to bypass governance a policy would
  otherwise enforce for the preferred-model/lowest-cost/quality-tier strategies.
* A cohort reassignment (e.g. rebalancing weights mid-experiment) changes historical
  subjects' assignments going forward — this is expected of any weight-based hashing
  scheme and is a known, documented characteristic, not a bug.
* Fallback (ADR-011) still applies on top of whichever candidate `ExperimentStrategy`
  selects as primary — fallback and experimentation are orthogonal, composable
  behaviors, not alternative strategies competing for the same decision point.

## Alternatives considered
* **Random per-request assignment** — rejected: not reproducible, and the same
  conversation could bounce between arms turn-to-turn, defeating the purpose of a
  cohort-based experiment.
* **External experiment-assignment service (e.g. a feature-flag platform)** — rejected
  for the base project: adds an external dependency and network call to the routing hot
  path for something a pure hash function accomplishes deterministically and for free;
  worth revisiting only if the project needed dynamic runtime rebalancing without a
  policy redeploy.
* **Sticky assignment via a persisted mapping (subject → arm) instead of a hash** —
  rejected: requires a stateful store and read before every routing decision, when a
  pure function gives the same stability without any I/O or storage cost.
