# ADR-010: Configuration storage approach

## Status
Accepted

## Context
The router depends on several kinds of configuration: application routing policies, the
model catalogue (capabilities, pricing, Regions, inference-profile identifiers), fallback
chains, and experiment configuration. This configuration needs explicit versioning, must
be usable in fast, credential-free local tests (Phase 2), and — once deployed — may need
runtime updates without a full redeploy. It must also stay cheap: the project should not
introduce a configuration service whose operational cost or complexity outweighs its
benefit at this scale.

## Decision
Configuration uses a versioned schema (see `docs/architecture/domain-glossary.md`) and
two storage modes for two different needs:

1. **Local development and tests**: version-controlled static configuration (JSON/YAML)
   packaged with the application under `policies/` and loaded directly — no AWS
   dependency, so the entire routing engine is testable offline (Phase 2).
2. **Deployed environments**: DynamoDB (preferred) or SSM Parameter Store, read by a
   `RoutingPolicyRepository`/`ModelCatalogue` adapter implementation, for cases where
   configuration needs to change without a redeploy (Phase 5+).

AWS AppConfig is deliberately not introduced unless a later phase demonstrates a concrete
operational need (e.g. safe deployment/rollback of configuration changes at a scale where
DynamoDB/Parameter Store direct reads become insufficient) that justifies its additional
complexity and cost.

## Consequences
* The domain/application layers depend only on the `RoutingPolicyRepository`/
  `ModelCatalogue` protocols (ADR-002); which storage backend is behind them is an
  adapter-level choice invisible to routing logic.
* Local tests and the CLI route evaluator (Phase 2) run with zero AWS dependency, which
  materially speeds up development and CI.
* Runtime configuration changes in deployed environments require a DynamoDB
  write/Parameter Store update rather than a full deployment, at the cost of needing to
  handle read consistency and caching considerations in that adapter (addressed when the
  adapter is built in Phase 5).
* Deferring AppConfig means the project does not get built-in gradual deployment/rollback
  of configuration changes out of the box; this is an explicit, documented trade-off,
  not an oversight — if it becomes a real need, it is a config-storage-adapter swap, not
  a domain change.

## Alternatives considered
* **AWS AppConfig from the start** — rejected for the initial scope: adds a service,
  deployment strategy, and cost surface beyond what a policy-driven router needs at this
  scale; DynamoDB/Parameter Store reads are sufficient for the configuration read
  patterns this project has (infrequent writes, read-heavy, small payloads).
* **Configuration solely in environment variables / CDK context** — rejected for deployed
  environments: does not support runtime updates without redeployment, and does not scale
  to per-application policies and a growing model catalogue.
* **A relational database for configuration** — rejected: contradicts the pay-per-request
  cost principle (ADR-005; no Aurora) and is unnecessary for what is fundamentally
  key-lookup configuration data.
