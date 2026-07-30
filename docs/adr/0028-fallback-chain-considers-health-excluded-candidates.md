# ADR-028: Fallback chain must apply even when the strategy selects nothing

## Status
Accepted

## Context
Phase 9's fault-injection testing (`tests/unit/application/test_load_and_fault_injection.py`)
simulated a sustained incident: repeated failures against the preferred model until
`InMemoryModelHealthRepository` (ADR-020) marked it `UNAVAILABLE`. With the default
`routing_strategy: preferred_model` (`PreferredModelStrategy`, `src/domain/strategy.py`),
this model is then excluded from the eligible-candidate set before selection ever runs.
`PreferredModelStrategy.select` only checks whether *its configured preferred alias* is
in the eligible set — by design (its docstring), it never substitutes a different eligible
candidate itself, since that is explicitly the fallback chain's job (Phase 4, ADR-011).

`InvocationOrchestrator._invoke_uncached` (pre-fix), however, short-circuited entirely
whenever `RoutingDecision.selected_model_alias` was `None`, returning
`InferenceResult(response=None, invocation_attempts=())` without ever consulting
`policy.fallback_policy.fallback_model_aliases`. The fallback chain (`_build_candidate_chain`)
was only ever invoked *after* a primary was selected and then failed at invocation time.

The combined effect: once a sustained incident pushed the preferred model to
`UNAVAILABLE`, every subsequent request failed outright — even with a perfectly healthy,
policy-approved fallback model sitting in the same eligible-candidate list. Model health
tracking, whose entire purpose is improving resilience during a sustained incident, was
making outcomes strictly worse than not tracking health at all (without health tracking,
the preferred model would still be attempted, fail at invocation time, and the existing
invocation-time fallback chain would correctly recover via the healthy alternate).

## Decision
`InvocationOrchestrator._build_candidate_chain` no longer requires a non-`None`
`selected_model_alias`. It now always starts from `decision.selected_model_alias` **if
present**, then appends `policy.fallback_policy.fallback_model_aliases` up to
`maximum_attempts`, filtered by eligibility — exactly as before, just no longer gated on
a primary selection existing. `_invoke_uncached` now builds this chain unconditionally
and only takes the empty-result short-circuit path when the chain itself is empty (i.e.
there is truly no eligible candidate at all — the original `REQUIRED_CAPABILITY_UNAVAILABLE`
and "nothing eligible for any reason" cases are unaffected, since in both the
candidate/eligible set is empty and the chain still comes out empty).

`_aggregate_decision` strips the stale `NO_ELIGIBLE_MODEL` reason code from the final
decision whenever it runs, since by construction it is only ever called once
`_build_candidate_chain` produced a non-empty chain — i.e. at least one eligible
candidate existed and was attempted, so "no eligible model" is no longer an accurate
description of the outcome, regardless of whether that attempt ultimately succeeded.

`PreferredModelStrategy` itself is unchanged, and its docstring's claim remains true: it
still never implicitly substitutes a candidate. The fix is entirely in the orchestrator,
which is where "substitute an approved alternate" (fallback) has always lived (ADR-011).

## Consequences
* A sustained health-driven exclusion of the preferred model now degrades to using the
  configured fallback model, exactly as a per-request invocation-time failure already
  did — the two failure paths (excluded before selection vs. fails after selection) now
  have consistent, symmetric recovery behavior.
* `RoutingDecision.fallback_used` and the `FALLBACK_SELECTED` reason code are set
  correctly in this path (the succeeded alias differs from the original, `None`,
  `selected_model_alias`), so the audit trail and dashboards distinguish this from a
  "clean" preferred-model success exactly as they already do for invocation-time
  fallback.
* If a policy configures no `fallback_model_aliases` at all, behavior is unchanged: an
  excluded preferred model with no fallback still yields `response=None` with
  `NO_ELIGIBLE_MODEL` — there was nothing else to try either before or after this fix.
* **Interaction with `ExperimentStrategy`** (found during Phase 9's multi-perspective
  self-review, not the original fault-injection pass): this fix applies uniformly in
  the orchestrator regardless of which strategy produced the decision, so a policy
  combining `routing_strategy: experiment` with a non-empty `fallback_policy` can now
  have its assigned arm silently-from-the-strategy's-perspective replaced by a fallback
  model if that arm becomes health-excluded — the exact substitution
  `ExperimentStrategy`'s own docstring says it never performs itself. This is judged
  acceptable, not a new bug to fix, because the substitution is never silent
  end-to-end: `fallback_used`/`FALLBACK_SELECTED` are always set, so experiment analysis
  requiring strict arm purity can filter on `fallback_used` from the same audit trail
  every other analysis already relies on. See `src/domain/strategy.py`'s
  `ExperimentStrategy` docstring for the same note. No shipped sample policy currently
  combines these two settings.
* Regression test: `test_fallback_used_when_preferred_model_is_excluded_by_health_before_selection`
  (`tests/unit/application/test_invocation_orchestrator.py`) pins this exact scenario
  directly against the real `InMemoryModelHealthRepository` adapter, not just a fake.

## Alternatives considered
* **Make `PreferredModelStrategy` itself fall back to another eligible candidate** —
  rejected: conflates two independently-configured, independently-reasoned mechanisms
  (routing strategy selection vs. the policy's explicit fallback chain), and would make
  `LowestCostStrategy`/`QualityTierStrategy` (which already consider the full eligible
  set) inconsistent with `PreferredModelStrategy` in a new, harder-to-explain way.
* **Leave as documented behavior, not a bug** — rejected: this isn't a deliberate
  trade-off like ADR-020's fleet-wide-visibility limitation, it's a straightforward
  correctness gap that defeats the stated purpose of the health signal it interacts
  with, caught by exactly the kind of fault-injection test Phase 9 exists to add.
