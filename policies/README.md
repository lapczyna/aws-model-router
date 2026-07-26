# Policies

Version-controlled, static routing policy and model catalogue configuration used for
local development, tests, and the Phase 2 CLI route evaluator — no AWS dependency.

This directory holds, once populated in Phase 2:

* **Application routing policies** — per-application allowed capabilities, model
  allowlists, quality tiers, cost/token limits, fallback policy, experiment configuration.
* **Model catalogue** — logical capability → model alias → concrete identifier
  (direct model ID / inference profile) mappings, `ModelCapabilities`, and versioned
  `ModelPricing`.

See [`docs/architecture/domain-glossary.md`](../docs/architecture/domain-glossary.md) for
the schema these files implement, and
[ADR-010](../docs/adr/0010-configuration-storage-approach.md) for why static,
version-controlled configuration is used here versus DynamoDB/Parameter Store for
deployed environments.
