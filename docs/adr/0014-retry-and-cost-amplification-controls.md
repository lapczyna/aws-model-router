# ADR-014: Retry and cost-amplification controls

## Status
Accepted

## Context
Two independent retry mechanisms now exist in the system: `adapters.bedrock.retry
.RetryPolicy` (Phase 3), which bounds retries of the *same* model on a transient/
throttled/timeout failure, and the Phase 4 fallback chain, which tries *different*
models on an eligible failure. Composed naively, these multiply: a fallback chain of 3
models, each internally retrying up to 3 times, is up to 9 billable Bedrock invocations
for one logical client request — exactly the "retry amplification" the original project
scope warns against.

## Decision
The two mechanisms are deliberately layered with a single bound each, not a combined
budget threaded through both:

* **`RetryPolicy.max_attempts`** (Phase 3, unchanged) bounds retries of one model for
  transient/throttled/timeout failures, with full-jitter exponential backoff. This is
  entirely internal to `BedrockModelProvider.invoke()` — from the fallback
  orchestrator's point of view, one call to `invoke()` is one logical attempt,
  regardless of how many times it retried internally before returning or raising.
* **`FallbackPolicy.maximum_attempts`** (Phase 4) bounds the number of *distinct
  models* tried per logical request (primary plus fallbacks). This single field serves
  both roles the original scope names separately — "maximum invocation attempts" and
  "retry budget" — because, given the layering above, bounding the fallback chain
  length *is* the request-level retry budget: each chain entry already carries its own
  fixed, independently-bounded retry cost from `RetryPolicy`.
* Fallback candidates are drawn only from the model catalogue's already-computed
  *eligible* set for this request (ADR-011) — cost eligibility is never re-evaluated
  more leniently just because earlier attempts failed.
* A `PERMANENT` failure at any position in the chain stops it immediately (ADR-011) —
  no amount of budget is spent retrying an error retrying cannot fix.

The worst-case cost multiplier for one logical request is therefore
`FallbackPolicy.maximum_attempts × RetryPolicy.max_attempts` Bedrock calls — a fixed,
computable, and documented ceiling, not an open-ended retry loop.

## Consequences
* Operators can reason about worst-case request cost/latency from two small config
  values without tracing internal retry counts across layers.
* No new "global attempt counter" threading is required between
  `BedrockModelProvider` and `InvocationOrchestrator` — each stays in charge of
  bounding its own layer, keeping the Phase 3 provider adapter unchanged and the
  Phase 4 orchestrator's contract with it simple (one `invoke()` call per chain entry).
* The default `FallbackPolicy` (`maximum_attempts=1`, empty
  `fallback_model_aliases`) means fallback is opt-in per application — the amplification
  ceiling for an application that hasn't configured fallback is exactly
  `RetryPolicy.max_attempts` (Phase 3's existing bound), unchanged from before Phase 4.
* Because each chain entry's retry budget is fixed by `RetryPolicy` rather than
  shrinking as the chain progresses, a pathological configuration (e.g.
  `maximum_attempts=10`) can still authorize a high worst-case multiplier — this is a
  policy-authoring responsibility, not a code-level guard; `docs/cost/` (Phase 6) will
  document recommended ceilings.

## Alternatives considered
* **A single, global attempt budget shared across all layers** (e.g. "12 total Bedrock
  calls, however distributed between fallback and per-model retry") — rejected:
  requires `BedrockModelProvider` to accept and decrement a caller-supplied remaining
  budget, breaking the clean separation between "this adapter reliably invokes one
  model" and "this orchestrator tries several models" — meaningfully more complex for
  a bound that a fixed multiplier already achieves.
* **No fallback-level bound, only per-model `RetryPolicy`** — rejected: an unbounded
  `fallback_model_aliases` list configured by policy could otherwise be walked
  entirely on every request, with no ceiling on fallback chain length.
* **Reduce `RetryPolicy.max_attempts` for later chain entries** (e.g. only 1 retry for
  fallback #2) — rejected as unnecessary complexity: the fixed multiplier is already a
  documented, computable ceiling, and asymmetric retry budgets per chain position would
  need their own justification and configuration surface without a clear benefit.
