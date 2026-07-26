# ADR-011: Fallback eligibility

## Status
Accepted

## Context
When a model invocation fails, blindly retrying against a different model risks masking
real problems (a malformed request will fail identically against any model), amplifying
cost (every fallback attempt is a billable Bedrock call), and violating governance (a
model excluded for cost or capability reasons must never be reached by "trying harder").
Phase 3 already classifies every provider failure into a `ProviderErrorCategory`
(`THROTTLED`, `TRANSIENT`, `TIMEOUT`, `PERMANENT`); Phase 4 needs a firm rule for which of
these are eligible for fallback.

## Decision
Fallback is attempted only for invocation failures classified `THROTTLED`, `TRANSIENT`,
or `TIMEOUT`. A `PERMANENT` failure stops the fallback chain immediately, regardless of
position (primary or a later fallback candidate) — `application.invocation_orchestrator.
InvocationOrchestrator` breaks out of its attempt loop the moment a `PERMANENT` category
is seen.

Every other case in the original "do not fall back after" list — policy denial, cost
rejection, unsupported capability, malformed configuration, validation failure — never
reaches the fallback loop at all, because it is resolved *before* invocation:

* Validation failure: rejected by `InferenceRequest`'s Pydantic validation, before
  `InvocationOrchestrator.invoke()` does anything.
* Policy denial / unsupported capability / cost rejection: `RouteEvaluationService`
  (Phase 2) already excludes ineligible candidates during routing; if no candidate
  remains, `decision.selected_model_alias` is `None` and `InvocationOrchestrator`
  returns immediately without attempting any invocation.
* Malformed configuration: raises `ConfigurationError` from policy/catalogue resolution,
  propagated unchanged — never caught by the fallback loop's `except ProviderError`.
* Authorization failure: not yet a domain concept (Phase 5, API Gateway/handler layer);
  when introduced, it will be resolved before routing, same shape as the above.

Additionally, a fallback candidate is only ever drawn from the candidates
`RouteEvaluationService` already marked `eligible=True` for *this specific request* —
the same capability/allowlist/token/cost checks that gated the primary selection also
gate every fallback candidate. A configured fallback alias that is not currently
eligible (e.g. its estimated cost exceeds the request's budget) is skipped, never
attempted.

## Consequences
* Fallback is fully policy-controlled: an application with an empty
  `fallback_policy.fallback_model_aliases` (the default) never falls back, no matter
  what fails.
* No case in the "do not fall back after" list needs special-case handling inside the
  fallback loop itself — each is structurally prevented from ever reaching it.
* A fallback candidate's cost/capability eligibility is computed exactly once (during
  route evaluation) and reused, rather than re-checked at invocation time — consistent
  and avoids duplicated filtering logic.
* Because eligibility is fixed at route-evaluation time, a fallback candidate that
  *becomes* eligible only after routing decisions were computed (e.g. a cost limit that
  would newly admit it) is not reconsidered mid-request — acceptable, since routing and
  invocation happen within the same request lifecycle.

## Alternatives considered
* **Retry the same model on any failure category, including permanent** — rejected:
  guarantees repeating an unfixable failure (e.g. a validation error Bedrock itself
  rejects) at additional latency and cost for no chance of success.
* **Let the fallback loop re-derive eligibility per candidate at invocation time** —
  rejected: duplicates `domain.filtering` logic in a second location, risking the two
  checks drifting apart; reusing `RouteEvaluationService`'s already-computed eligible
  set is simpler and keeps a single source of truth for "is this candidate allowed".
