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

Every row above is a real, executed test — not aspirational. Run
`python -m pytest tests/unit/application tests/unit/adapters/bedrock tests/unit/handlers -q`
to re-verify all of them together.

## Deliberately not yet covered (Phase 9 scope)

* **Load testing** (sustained concurrent traffic against a real deployed stack) — this
  project's unit tests exercise fallback/idempotency logic deterministically with fake
  providers; they do not measure real Lambda cold-start distribution, real API Gateway
  throttling behavior under load, or real DynamoDB capacity behavior at scale.
* **Fault injection against a live deployment** (e.g. actually throttling a real Bedrock
  model, or killing a Lambda execution environment mid-request) — everything above is
  simulated via fakes/stubs; a live fault-injection exercise against a deployed `dev`
  stack would validate the same logic under real AWS conditions, not just simulated
  ones.
* **Multi-Region failover drill** — contingent on adopting cross-Region inference
  profiles (ADR-023), not yet built.

These are explicitly deferred to Phase 9 ("load testing, fault injection") per
`PROJECT_PLAN.md`, not silently skipped — Phase 7's resilience scope is the
already-tested unit-level failure-mode coverage above, which is real and complete for
what a credential-free, deterministic test suite can prove.
