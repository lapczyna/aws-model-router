# Security documentation

* [`threat-model.md`](threat-model.md) — 22 threats across 5 trust boundaries plus AI
  content safety, each with an existing mitigation, residual risk, and status
  (Mitigated/Accepted/Deferred). Start here.
* [`security-architecture.md`](security-architecture.md) — a narrative walkthrough of
  the security posture layer by layer, following the client-request path.
* [`resilience-test-plan.md`](resilience-test-plan.md) — what failure modes are already
  covered by real, executed tests (fallback, idempotency, model health, abuse cases),
  and what's deliberately deferred to Phase 9 (load testing, live fault injection).

See [`SECURITY.md`](../../SECURITY.md) at the repository root for the current
vulnerability-reporting policy, [`docs/operations/incident-response.md`](../operations/incident-response.md)
and [`docs/operations/disaster-recovery.md`](../operations/disaster-recovery.md) for
response procedures, and the ADRs referenced throughout both documents above
(especially [ADR-015](../adr/0015-api-authorization-model.md),
[ADR-022](../adr/0022-least-privilege-iam-review.md),
[ADR-023](../adr/0023-cross-region-inference-profile-resilience.md), and
[ADR-024](../adr/0024-responsible-ai-gateway-placement.md)) for the full decision
records.
