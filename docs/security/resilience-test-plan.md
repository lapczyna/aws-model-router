# Resilience test plan

What failure modes this project already tests against, how, and what remains for
dedicated load/fault-injection testing (Phase 9). See
[`threat-model.md`](threat-model.md) for the security-specific failure modes and
[`disaster-recovery.md`](../operations/disaster-recovery.md) for recovery procedures
once a failure has actually occurred.

## Already tested (unit-level, deterministic, no real AWS calls)

| Failure mode | Test | What it proves |
|---|---|---|
| Primary model throttled | `test_primary_throttled_and_fallback_succeeds` (`tests/unit/application/test_invocation_orchestrator.py`) | Fallback to an approved alternate model succeeds automatically |
| Primary model transient error | `test_primary_transient_failure_and_fallback_succeeds` | Same, for a different retryable category |
| Non-retryable (permanent) failure | `test_non_retryable_failure_does_not_fallback` | The chain stops immediately — no wasted fallback attempts on an error fallback can't fix |
| Fallback chain length exceeded | `test_fallback_limit_enforced` | `FallbackPolicy.maximum_attempts` is a hard ceiling, not advisory |
| All eligible models fail | `test_all_eligible_models_fail` | Returns a clean `response=None` result, not an unhandled exception |
| Concurrent duplicate requests | `test_concurrent_duplicate_requests_only_invoke_model_once` (real `threading`, not mocked) | Idempotency dedup holds under genuine concurrency, not just sequential calls |
| Idempotency reservation leak on crash | `test_idempotency_reservation_is_released_on_unexpected_failure` | A mid-request exception releases the reservation rather than permanently blocking the key |
| Cost-ineligible fallback candidates | `test_fallback_skips_candidates_ineligible_on_cost` | A fallback chain never silently exceeds the cost limit the primary was bound by |
| Bedrock throttling/timeout/malformed response | `tests/unit/adapters/bedrock/test_retry.py`, `test_bedrock_model_provider.py` (via `botocore.stub.Stubber`) | The provider adapter's own retry/backoff and error classification, independent of the orchestrator |
| Model health degradation | `tests/unit/adapters/memory/test_in_memory_model_health_repository.py`, `tests/unit/domain/test_filtering.py` | Consecutive failures correctly transition `HEALTHY → DEGRADED → UNAVAILABLE` and affect (or don't) eligibility |
| Adversarial/malformed input | `tests/unit/handlers/test_abuse_cases.py` (Phase 7) | Oversized/malformed bodies, unrecognized fields, and adversarial path parameters all degrade to a clean 4xx, never a 500 or data leak |
| High-concurrency idempotency correctness (50 threads, same key) | `test_fifty_concurrent_duplicate_requests_only_invoke_model_once` (`tests/unit/application/test_load_and_fault_injection.py`) | The single-invocation guarantee holds at higher concurrency than the original 2-thread test, not just in principle |
| Randomized fault injection, sequential (200 requests, seeded random failure rates per model) | `test_two_hundred_sequential_requests_under_random_faults_never_exceed_fallback_bound` | Fallback attempt counts stay bounded by `maximum_attempts` and both fallback-used and clean-success outcomes occur, across many independent decisions, not just one hand-picked scenario |
| Randomized fault injection, concurrent (100 requests, 20 worker threads) | `test_concurrent_requests_under_random_faults_never_raise_unexpectedly` | No uncaught exceptions or attempt-count violations under genuine concurrent load with randomized failures |
| Sustained single-model incident (health-based exclusion) | `test_sustained_primary_failures_eventually_stop_being_attempted_at_all`, `test_fallback_used_when_preferred_model_is_excluded_by_health_before_selection` (`test_invocation_orchestrator.py`) | Once a model is marked `UNAVAILABLE`, later requests skip it entirely (no wasted invocation) **and** still recover via a healthy configured fallback model — see ADR-028 for a real gap this testing found and fixed: before the fix, health-based exclusion of the preferred model caused total request failure even with a healthy fallback available |
| Throughput sanity (500 sequential requests) | `test_five_hundred_sequential_requests_complete_in_a_generous_time_bound` | Catches a gross performance regression (e.g. accidental O(n²) behavior); not a precise benchmark — see `docs/performance/` for that |

Every row above is a real, executed test — not aspirational. Run
`python -m pytest tests/unit/application tests/unit/adapters/bedrock tests/unit/handlers -q`
to re-verify all of them together.

## Deliberately not yet covered (requires a real deployed stack)

* **Load testing against a real deployed stack** (sustained concurrent traffic hitting
  actual API Gateway/Lambda/DynamoDB) — the in-process concurrency and fault-injection
  tests above prove the routing/fallback/idempotency *logic* holds under genuine thread
  concurrency and randomized failures; they do not measure real Lambda cold-start
  distribution, real API Gateway throttling behavior under load, or real DynamoDB
  capacity behavior at scale. That requires an actual `cdk deploy`, which remains the
  user's action, not something this project performs on its own.
* **Fault injection against a live deployment** (e.g. actually throttling a real Bedrock
  model, or killing a Lambda execution environment mid-request) — everything above is
  simulated via fakes/stubs; a live fault-injection exercise against a deployed `dev`
  stack would validate the same logic under real AWS conditions, not just simulated
  ones.
* **Multi-Region failover drill** — contingent on adopting cross-Region inference
  profiles (ADR-023), not yet built.

These remain genuinely deferred — they require a live AWS deployment this project does
not perform on its own — not silently skipped. Everything achievable without one is now
covered above, including higher-concurrency and randomized-fault-injection scenarios
added in Phase 9 (`tests/unit/application/test_load_and_fault_injection.py`).
