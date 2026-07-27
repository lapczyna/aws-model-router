"""DynamoDB-backed implementations of `IdempotencyStore` and `RoutingDecisionRepository`
(ADR-018) — multi-instance-safe (via DynamoDB conditional writes), unlike the
single-process `adapters.memory` reference implementations from Phase 4.
"""
