"""In-memory reference implementations of `IdempotencyStore` and
`RoutingDecisionRepository` (ADR-010, ADR-013) — for local development, tests, and
single-instance deployments. State is process-local; a DynamoDB-backed implementation
suitable for multi-instance production use is Phase 5 scope.
"""
