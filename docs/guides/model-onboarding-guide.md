# Model onboarding guide

How to add a new model to `policies/model_catalogue.yaml` (`src/domain/catalogue.py`).
Clients never see this file or any value in it — they request logical capabilities
(e.g. `"balanced-text"`), and the router resolves them to a `model_alias` here
(ADR-006).

## Required shape

```yaml
- model_alias: my-new-model-primary       # unique, stable — never a real provider model ID
  provider: bedrock                        # only bedrock is implemented today (ADR-003)
  region: us-east-1
  resolution:
    type: direct_model_id                  # see "Resolution types" below
    value: anthropic.claude-3-haiku-20240307-v1:0
  capabilities:
    capability_tags: [economical-text]     # at least one; what allowed_capabilities matches against
    quality_tier: standard                  # standard | premium
    max_input_tokens: 200000
    max_output_tokens: 4096
    supports_tool_use: false
    supports_structured_output: false
    supports_streaming: true
    supported_modalities: [text]
    typical_latency: low                    # low | balanced | high — a configured
                                             # classification, not a measured guarantee
  pricing:
    currency: USD
    input_price_per_1k_tokens: "0.00025"    # quoted string — see the note below
    output_price_per_1k_tokens: "0.00125"
    pricing_version: 1
  health:
    status: healthy
```

**Pricing values must be quoted strings**, not bare numbers — an unquoted YAML number
parses as a lossy binary float and is rejected at validation time (`src/domain/money.py`).

## Resolution types

* **`direct_model_id`** — `value` is a real Bedrock foundation-model ID
  (`anthropic.claude-3-haiku-20240307-v1:0`). Simplest; used by every sample model today.
* **`cross_region_inference_profile`** — `value` is a cross-Region inference profile ID.
  See [ADR-023](../adr/0023-cross-region-inference-profile-resilience.md) — evaluated,
  not yet adopted by the base deployment.
* **`application_inference_profile`** — `value` is an application inference profile ID,
  the recommended mechanism for attributing real Bedrock spend to a specific application
  in AWS Cost Explorer. See `docs/cost/cost-estimation-guide.md`'s "Application inference
  profiles for cost attribution".
* **`router_alias`** — `value` names another catalogue entry's `model_alias`, resolved
  through one bounded hop by `BedrockModelProvider`. Names no ARN of its own.

## What happens automatically once the catalogue entry exists

* **IAM permissions**: `infrastructure/cdk_constructs/lambda_construct.py`'s
  `_load_bedrock_resource_arns` parses this file **at `cdk synth` time** and scopes the
  Lambda execution role's `bedrock:InvokeModel`/`Converse`/`ConverseStream` grant to
  exactly the ARNs your catalogue declares — `direct_model_id` becomes
  `arn:aws:bedrock:{region}::foundation-model/{value}`,
  `cross_region_inference_profile`/`application_inference_profile` become
  `arn:aws:bedrock:{region}:{account}:inference-profile/{value}`. No manual IAM policy
  edit is needed or expected — adding a model here is sufficient (ADR-022's
  least-privilege review; `docs/requirements.md` NFR-2.2).
* **`GET /v1/models`**: automatically lists the new model (capabilities, quality tier,
  typical latency — never the raw `resolution.value`).
* **Routing eligibility**: any policy with the matching `capability_tags` entry in its
  `allowed_capabilities` and this `model_alias` in its `allowed_model_aliases` can now
  route to it.

## What you still need to do yourself

1. Add the alias to any `RoutingPolicy.allowed_model_aliases` that should be able to use
   it — a new catalogue entry grants no application access by itself (see
   [`policy-authoring-guide.md`](policy-authoring-guide.md)).
2. Bump `pricing_version` on any *change* to an existing entry's pricing (new entries
   start at `1`) — see `docs/cost/cost-estimation-guide.md`'s "Keeping pricing current".
3. Redeploy (`docs/operations/deployment-and-teardown.md`) — there is no live,
   database-backed catalogue store in the base deployment (ADR-010's Phase 5+ scope was
   deliberately not built).

## Testing locally

```bash
python scripts/evaluate_route.py --request <a request targeting the new capability/model>
python scripts/cost_comparison_report.py     # see where the new model lands cost-wise
cd infrastructure && CDK_NAG_ENABLED=true cdk synth -c env=dev --quiet   # confirms the
                                                                          # catalogue parses
                                                                          # and IAM synthesizes
```

No AWS credentials are required for any of the above.
