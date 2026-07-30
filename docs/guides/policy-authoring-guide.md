# Policy authoring guide

How to write or modify a `RoutingPolicy` (`src/domain/policy.py`). See
[`application-onboarding-guide.md`](application-onboarding-guide.md) for the
higher-level "onboard a whole new application" workflow this guide's mechanics slot
into, and [`../architecture/domain-glossary.md`](../architecture/domain-glossary.md) for
the domain vocabulary used below.

## Where policies live

`policies/default_policy.yaml` is the fallback used for any `application_id` without its
own file. `policies/applications/<application_id>.yaml` (or `.yml`/`.json`) is a
dedicated policy for one application — see
[`LocalFileRoutingPolicyRepository`](../../src/adapters/config/local_policy_repository.py)
for the exact resolution order.

## Required fields

```yaml
policy_id: my-app-default          # a stable identifier, not necessarily the applicationId
policy_version: 1                  # bump on every change (audit records capture it)
allowed_capabilities: [balanced-text]     # at least one; must match a capability_tags
                                           # entry in policies/model_catalogue.yaml
allowed_model_aliases: [balanced-text-primary]  # at least one
allowed_quality_tiers: [standard]         # at least one: standard | premium
default_quality_tier: standard            # must be one of allowed_quality_tiers
maximum_estimated_cost_usd: "0.01"        # quoted string — see the note below
maximum_output_tokens: 1000
routing_strategy: preferred_model          # preferred_model | lowest_cost | quality_tier | experiment
```

**Pricing/cost values must be quoted strings** (`"0.01"`, not `0.01`) — an unquoted YAML
number parses as a lossy binary float and is rejected at validation time (see
`src/domain/money.py`).

## Choosing a routing strategy

* **`preferred_model`** — always selects one specific model when it's eligible; requires
  `preferred_model_alias` (must be in `allowed_model_aliases`). Never substitutes a
  different model itself if the preferred one is ineligible — pair it with
  `fallback_policy` below if you want automatic recovery, not silent failure.
* **`lowest_cost`** — always selects the cheapest eligible candidate for the request,
  ties broken by `model_alias`. Naturally adapts if a cheaper eligible model becomes
  available or the preferred one becomes ineligible, without needing a `fallback_policy`
  at all (see `support-assistant.yaml` for a real example, and
  `policies/README.md`'s note on strategy coverage).
* **`quality_tier`** — selects among candidates matching a target quality tier. See
  `tests/unit/domain/test_strategy.py` for its unit-level behavior; no sample
  application currently uses it.
* **`experiment`** — deterministic, weighted A/B assignment across named arms; requires
  `experiment_policy` (see `experimental-app.yaml` for a real example and
  [ADR-012](../adr/0012-deterministic-experimentation.md)).

## Fallback

```yaml
fallback_policy:
  fallback_model_aliases: [balanced-text-secondary]  # must be in allowed_model_aliases
  maximum_attempts: 2                                 # total chain length, including primary
```

Fallback only applies to `THROTTLED`/`TRANSIENT`/`TIMEOUT` invocation failures, and only
to configured aliases that are themselves eligible for the specific request (same
capability/cost/quality-tier checks as the primary) — see
[ADR-011](../adr/0011-fallback-eligibility.md), and
[ADR-028](../adr/0028-fallback-chain-considers-health-excluded-candidates.md) for the
case where the preferred model is excluded by health tracking before selection rather
than failing at invocation time.

## Idempotency

```yaml
idempotency_policy:
  allow_response_caching: true   # cache the full response for a repeated idempotency_key
  retention_seconds: 300
```

See [ADR-013](../adr/0013-idempotency-strategy.md).

## Client override permissions

```yaml
allow_client_overrides:
  quality_tier: false
  maximum_estimated_cost_usd: true   # a client can only tighten this, never loosen it
  maximum_output_tokens: true
  latency_preference: false
```

A client-requested value is used only if the matching permission is `true`, and even
then only as a *tightening* of the policy's own limit — never a way to exceed it (see
`domain.requirements.resolve_effective_requirements`).

## Testing a policy change locally

```bash
python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
```

Write a request JSON file targeting your application (`scripts/examples/README.md` shows
the shape) and confirm the resulting `RoutingDecision` — selected model, reason codes,
every candidate's eligibility — matches what you intended, before deploying. No AWS
credentials required. See `tests/contract/test_policy_schema_examples.py` for how policy
files are validated in CI.
