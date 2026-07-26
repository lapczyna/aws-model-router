# Policies

Version-controlled, static routing policy and model catalogue configuration used for
local development, tests, and the CLI route evaluator (`scripts/evaluate_route.py`) —
no AWS dependency.

* [`model_catalogue.yaml`](model_catalogue.yaml) — the model catalogue: logical
  capability → model alias → concrete identifier (direct model ID / inference profile)
  mappings, `ModelCapabilities`, and versioned `ModelPricing`. Loaded by
  `adapters.config.local_model_catalogue.LocalFileModelCatalogue`.
* [`default_policy.yaml`](default_policy.yaml) — the fallback `RoutingPolicy` used for
  any application without its own file below.
* [`applications/`](applications/) — one file per application, named
  `<applicationId>.yaml` (or `.yml`/`.json`), each a `RoutingPolicy`. Loaded by
  `adapters.config.local_policy_repository.LocalFileRoutingPolicyRepository`.
  - `support-assistant.yaml` — `lowest_cost` strategy, plus a `fallback_policy`
    configuring `balanced-text-secondary` as a backup for `balanced-text-primary`
    (ADR-011).
  - `experimental-app.yaml` — `experiment` strategy, weighted 70/30 between
    `balanced-text-primary` and `balanced-text-secondary` (ADR-012).

Pricing values in these files must be quoted strings (e.g. `"0.00025"`), not bare
numbers — see `src/domain/money.py` for why (unquoted YAML numbers parse as a lossy
binary float, which is rejected at validation time).

See [`docs/architecture/domain-glossary.md`](../docs/architecture/domain-glossary.md) for
the domain model these files implement, and
[ADR-010](../docs/adr/0010-configuration-storage-approach.md) for why static,
version-controlled configuration is used here versus DynamoDB/Parameter Store for
deployed environments (Phase 5).
