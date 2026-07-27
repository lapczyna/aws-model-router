"""In-memory reference implementations of `IdempotencyStore`, `RoutingDecisionRepository`
(ADR-010, ADR-013), and `ModelHealthRepository` (ADR-020) — for local development,
tests, and single-instance deployments. State is process-local; `IdempotencyStore`/
`RoutingDecisionRepository` gained DynamoDB-backed, multi-instance-safe implementations
in Phase 5 (`adapters.dynamodb`) — `ModelHealthRepository` deliberately has not (ADR-020
documents why a process-local health signal is an acceptable trade-off for now).
"""
