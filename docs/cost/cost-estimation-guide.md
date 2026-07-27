# Cost estimation guide

How the router estimates cost, why that estimate diverges from actual AWS billing, how
pricing configuration is kept current, and how retries/fallback can multiply real
Bedrock spend for a single logical request.

## How estimation works

`domain.cost_estimation.DefaultCostEstimator` computes
`EstimatedCost` as a pure function of `Usage` (input/output token counts) and a model's
`ModelPricing` (`policies/model_catalogue.yaml`, per-1k-token input/output prices,
`Decimal`-typed — never `float`, to avoid binary floating-point rounding error in a cost
figure). `DefaultTokenEstimator` derives `Usage` itself:

* **Input tokens**: `ceil(total_message_characters / 4)` — a fixed, deterministic
  heuristic, not a real tokenizer for the specific model in use.
* **Output tokens**: the request's *requested maximum* (`maximumOutputTokens`), not the
  number of tokens the model actually generates.

Every `EstimatedCost` this produces is exactly that — an estimate — and is labeled as
such everywhere it's surfaced (`estimatedCostUsd` in API responses, `EstimatedCostUsd`
in metrics/dashboards). ADR-005 established this project-wide: never presented as, or
substitutable for, actual AWS billing.

## Why the estimate diverges from actual billing

* **Output tokens are the requested cap, not the actual count.** A request with
  `maximumOutputTokens: 500` that the model completes in 120 tokens is estimated at the
  500-token price — the estimate is a worst-case *ceiling* for output cost, not a
  prediction of what the model will actually produce.
* **Input tokens are a character-count heuristic**, not the specific model's real
  tokenizer — different models/providers tokenize the same text into different token
  counts (subword vocabularies differ), so the `chars_per_token = 4` approximation is
  reasonable on average English text but not exact for any specific model.
* **Bedrock pricing itself can differ from the configured `pricing_version`** if AWS
  changes list pricing between when `policies/model_catalogue.yaml` was last updated and
  when a request is actually served (see "Keeping pricing current" below).
* **Cross-Region inference profiles and provisioned throughput** (not used in the base
  deployment — ADR-005) can carry different effective pricing than direct on-demand
  model pricing; the catalogue's `input_price_per_1k_tokens`/`output_price_per_1k_tokens`
  must reflect whichever resolution type (`ModelResolutionType`) a catalogue entry
  actually uses.

For real billed cost, use **AWS Cost Explorer** or **AWS Budgets**, not this router's
estimates. The router's `ModelRouter EstimatedCostUsd` metric
(`docs/operations/observability.md`) is a *trend/guidance* signal — useful for noticing
"spend is climbing" quickly, not a reconciliation source.

## Keeping pricing current

`ModelPricing.pricing_version` is a required, incrementing integer
(`policies/model_catalogue.yaml`) — bump it whenever `input_price_per_1k_tokens` or
`output_price_per_1k_tokens` changes, so a stale estimate is at least distinguishable
from a current one if ever compared side by side (e.g. across two `AuditRecord`s taken
before/after a pricing update). There is no automatic pricing feed — AWS Bedrock pricing
changes are applied by editing this file and redeploying
(`docs/operations/deployment-and-teardown.md`), the same as any other policy/catalogue
change (ADR-010's Phase 5+ live-config-store scope was deliberately not built — see
`PROJECT_PLAN.md`'s Open Assumptions).

## Retry/fallback cost multiplication

A single logical `POST /v1/inference` call can result in more than one real Bedrock
invocation: `RetryPolicy.max_attempts` (default 3, `src/adapters/bedrock/retry.py`)
bounds retries *within* one model's invocation, and `FallbackPolicy.maximum_attempts`
(`RoutingPolicy.fallback_policy`) bounds how many different models in the fallback chain
are tried. The worst-case number of real Bedrock invocations for one request is:

```
FallbackPolicy.maximum_attempts × RetryPolicy.max_attempts
```

This is a fixed, computable ceiling — never an open-ended retry loop (ADR-014). When
budgeting for worst-case spend under a provider incident (sustained throttling causing
every attempt to exhaust its retries before failing over), multiply a policy's
per-invocation cost expectation by this ceiling, not by 1.

## Application inference profiles for cost attribution

AWS Bedrock **application inference profiles** (`ModelResolutionType.APPLICATION_INFERENCE_PROFILE`,
already supported by `BedrockModelProvider` and the catalogue schema since Phase 2/3)
tag invocations with a profile identifier that AWS Cost Explorer can break out
per-profile — the recommended mechanism for attributing real Bedrock spend back to a
specific logical use case or application, more reliable than trying to reconstruct it
from CloudWatch Logs Insights queries over `ApplicationId`/`Capability` alone. The base
`policies/model_catalogue.yaml` sample configuration uses `direct_model_id` resolution
for simplicity/illustration; adopting application inference profiles for real cost
attribution is a `policies/model_catalogue.yaml` configuration change (creating the
profile in Bedrock, then setting `resolution.type: application_inference_profile` and
`resolution.value` to its identifier) — no router code change required.
