"""Local, file-backed implementations of the configuration ports.

These read version-controlled JSON/YAML from disk (ADR-010) — no AWS dependency, so the
routing engine is fully testable and runnable offline. A DynamoDB/SSM-backed
implementation of the same `domain.ports.ModelCatalogue` / `RoutingPolicyRepository`
protocols is added in Phase 5 for deployed environments, without any change to the
domain or application layers.
"""
