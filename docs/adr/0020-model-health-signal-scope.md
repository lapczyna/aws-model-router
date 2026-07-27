# ADR-020: Model health signal — scope and derivation

## Status
Accepted

## Context
`ModelHealth`/`ModelHealthStatus` (`HEALTHY`/`DEGRADED`/`UNAVAILABLE`) and the
`MODEL_UNHEALTHY` reason code were modeled in the catalogue schema and reason-code
vocabulary since Phase 2, but deliberately left unwired — no `ModelHealthRepository`
existed to source a live signal from, and Phase 4's explicit scope (fallback,
experimentation, idempotency) did not include it (`PROJECT_PLAN.md`). Phase 6 is where a
real health signal, derived from observed invocation outcomes, first becomes available
(`domain-glossary.md`: "Sourced from observed invocation outcomes, not predictive
modeling").

## Decision
`domain.ports.ModelHealthRepository` is a two-method protocol: `get_health(model_alias)`
and `record_outcome(model_alias, status)`. `InvocationOrchestrator` calls
`record_outcome` after every invocation attempt; `domain.filtering.build_route_candidates`
calls `get_health` per candidate model and folds the result into eligibility.

**Derivation**: a per-model-alias consecutive-failure counter.
`InvocationAttemptStatus.SUCCEEDED` resets it to zero. `THROTTLED`, `TRANSIENT_ERROR`,
and `TIMEOUT` increment it. `NON_RETRYABLE_ERROR` (a `PERMANENT` provider failure) never
affects it — a permanent failure reflects the specific request (e.g. an unsupported
parameter), not the model's operational state, so it says nothing about whether the
*next* request to this model will succeed. `degraded_after`/`unavailable_after`
thresholds (default 3/5) map the counter to a `ModelHealthStatus`.

**Filtering effect** (`domain/filtering.py`): `UNAVAILABLE` excludes the candidate
(`eligible = False`, reason code `MODEL_UNHEALTHY`) — the existing single-code vocabulary
entry, now finally wired up. `DEGRADED` is informational only: the new
`MODEL_DEGRADED` reason code is added, but the candidate stays eligible. There is no
healthier alternative signal to prefer over a degraded model here (that would require
per-strategy scoring changes, out of scope for an observability phase) — `DEGRADED`
exists so operators can *see* a struggling model in the audit trail and dashboard before
it (potentially) becomes fully excluded, not to change routing outcomes by itself.

**Implementation**: `adapters.memory.InMemoryModelHealthRepository` — thread-safe,
single-process, matching the pattern `InMemoryIdempotencyStore`/
`InMemoryRoutingDecisionRepository` used before their DynamoDB-backed Phase 5
counterparts (ADR-018). Unlike those two, **no DynamoDB-backed implementation is planned
for `ModelHealthRepository`** at this time — see Consequences.

## Consequences
* **Scope limitation, accepted deliberately**: health state lives only within one Lambda
  execution environment's lifetime, not fleet-wide across every concurrent execution
  environment. Under real Lambda concurrency, a burst of throttling spread across many
  concurrently-invoked (possibly cold-started) execution environments will mostly *not*
  trip any single environment's local counter past its threshold — the aggregate
  fleet-wide health picture this feature conceptually promises is therefore only
  partially realized in a real deployment. This is unlike idempotency (ADR-013 → 018),
  where cross-instance correctness was a hard requirement (a race that isn't caught is a
  correctness bug); here, an occasionally-missed degradation is a soft signal quality
  gap, not a correctness bug — the router still functions correctly with or without it.
* A DynamoDB-backed, fleet-wide `ModelHealthRepository` remains straightforward to add
  later (implement the same protocol, no domain/application change needed — ADR-002's
  dependency inversion) if a genuine need is demonstrated (e.g. observed real-world
  throttling incidents the in-memory signal fails to catch). Not built speculatively now.
* `RouteEvaluationService`/`InvocationOrchestrator` both default
  `model_health_repository` to `None` (health status always `HEALTHY`, no filtering
  effect) — every pre-Phase-6 test and call site is unaffected without modification.
* `POST /v1/routes/evaluate` reflects the same health-based filtering as
  `POST /v1/inference` (both call through `RouteEvaluationService.evaluate`) — "explain
  what route would be selected" stays accurate to what would actually happen.

## Alternatives considered
* **DynamoDB-backed health store from the start** — rejected for Phase 6: adds a new
  table, new IAM grants, and read/write latency on every candidate evaluation, for a
  soft signal whose in-memory approximation is sufficient to demonstrate the mechanism
  and is honestly documented as scope-limited rather than silently wrong.
* **A `DEGRADED` reason code that also excludes the candidate** (collapsing to a single
  eligibility-affecting health state, like `UNAVAILABLE`) — rejected: throws away the
  distinction the domain-glossary's three-state model already established, and would
  make a model unavailable to callers based on a threshold weaker than genuine
  unavailability.
* **Scoring-based health weighting inside `RoutingStrategy`** (preferring healthier
  candidates over excluding/including) — rejected as out of scope for an observability
  phase; a real scope change to routing strategy selection, better justified alongside
  its own dedicated tests and reasoning once there's a concrete need.
