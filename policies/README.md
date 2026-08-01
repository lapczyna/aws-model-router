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
  - `multi-provider-demo.yaml` — `preferred_model` strategy **with** a configured
    `fallback_policy` that spans two different providers: `balanced-text-primary`
    (Bedrock) preferred, `balanced-text-openai` (OpenAI) as fallback (ADR-029, Phase
    10a). See `scripts/run_demo_scenarios.py --scenario multi-provider-fallback`.

Pricing values in these files must be quoted strings (e.g. `"0.00025"`), not bare
numbers — see `src/domain/money.py` for why (unquoted YAML numbers parse as a lossy
binary float, which is rejected at validation time).

## Routing-strategy coverage (Phase 9 sample policy review, updated Phase 10a)

Between them, these four files cover `preferred_model` both without a `fallback_policy`
(`default_policy.yaml`) and with one (`multi-provider-demo.yaml`, added Phase 10a),
`lowest_cost` (with a `fallback_policy` — `support-assistant.yaml`), and `experiment`
(`experimental-app.yaml`). One combination remains deliberately *not* represented by a
static sample file:

* `quality_tier` strategy — see `tests/unit/domain/test_strategy.py` for its unit-level
  coverage; no sample application currently uses it.

The health-excluded-preferred-model scenario (ADR-028) is demonstrated in code, not a
static file, since it needs a scripted health-repository setup rather than a fixed
request/response pair — see `scripts/run_demo_scenarios.py --scenario
health-degradation`.

See [`docs/architecture/domain-glossary.md`](../docs/architecture/domain-glossary.md) for
the domain model these files implement, and
[ADR-010](../docs/adr/0010-configuration-storage-approach.md) for why static,
version-controlled configuration is used here versus DynamoDB/Parameter Store for
deployed environments (Phase 5).
