# ADR-029: Multi-provider routing — OpenAI as the second provider

## Status
Accepted

## Context
ADR-002 established a provider-independent domain architecture specifically so a second
provider could be added later without rewriting the routing engine; ADR-003 deliberately
deferred building one, to prove depth in one AWS-native integration first. Phase 9
closed out the originally-scoped nine phases; `PROJECT_PLAN.md`'s Phase 10 named "advanced
extensions" as an explicit, unscoped, optional grab-bag of ~18 disparate ideas, not a
single deliverable. When asked to start Phase 10, the user was asked which specific
extension to scope as the first increment and chose multi-provider routing — the most
direct test of whether ADR-002's claim actually holds.

## Decision
**OpenAI** is the second provider, via its Chat Completions API. Chosen over a second
AWS-native option (e.g. a different Bedrock foundation model family) specifically
because it is a genuinely independent vendor with its own SDK, exception hierarchy, and
wire format — proving cross-vendor independence, not just cross-model-family independence
within Bedrock.

`OpenAIModelProvider` (`src/adapters/openai/`) implements `domain.ports.ModelProvider`,
mirroring `BedrockModelProvider`'s shape exactly:

* **Shared, provider-neutral helpers extracted to `src/adapters/common/`**
  (`model_resolution.py`: catalogue lookup, router-alias indirection, capability
  checking; `retry.py`: full-jitter exponential backoff; `error_messages.py`: fixed safe
  error text) — both adapters now use the identical implementation for everything that
  isn't provider-wire-format-specific, rather than duplicating it.
* **`adapters/openai/chat_completions_mapper.py`** maps `ProviderRequest`/
  `ProviderResponse` to/from OpenAI's `ChatCompletion` wire shape, the same role
  `adapters/bedrock/converse_mapper.py` plays for Bedrock (ADR-009).
* **`adapters/openai/error_mapping.py`** classifies `openai` SDK exceptions
  (`RateLimitError` → `THROTTLED`, `APITimeoutError` → `TIMEOUT`,
  `APIConnectionError`/5xx `APIStatusError` → `TRANSIENT`, everything else → `PERMANENT`)
  into the same `ProviderErrorCategory` taxonomy Bedrock uses — routing/fallback logic
  never needs to know which provider actually failed.

**`CompositeModelProvider`** (`src/adapters/composite_model_provider.py`) is the one new
concept: it resolves a request's model via the catalogue, then dispatches to whichever
registered provider adapter matches that model's `provider` field. Neither
`BedrockModelProvider` nor `OpenAIModelProvider` has any awareness the other exists —
`CompositeModelProvider` is the only place that does, and it is still just another
`ModelProvider` implementation from the application layer's point of view (ADR-002 holds
one level deeper than before).

**Catalogue/policy validation** (`src/domain/catalogue.py`,
`adapters/config/local_model_catalogue.py`) gained two new checks, both real correctness
gaps a multi-provider catalogue makes possible for the first time: a non-Bedrock model
can't declare a Bedrock-specific `resolution.type` (`cross_region_inference_profile`/
`application_inference_profile`), and a `router_alias` can't target a model belonging to
a different provider (the alias's own `provider` field is what `CompositeModelProvider`
dispatches on, so a cross-provider target would silently send the wrong wire format to
the wrong API).

**Infrastructure** (`infrastructure/cdk_constructs/lambda_construct.py`): an OpenAI API
key is stored in a Secrets Manager secret, provisioned *only* if
`policies/model_catalogue.yaml` actually declares an `openai` model — a Bedrock-only
deployment never pays for a secret it doesn't need. `Secret.grant_read()` scopes
`secretsmanager:GetSecretValue` to that one secret's ARN, never a wildcard. Fixed a real,
previously-latent bug while making this change: `_load_bedrock_resource_arns` iterated
*every* catalogue entry regardless of `provider` — before this phase harmless (only
Bedrock entries existed), but would have built a meaningless/incorrect
`arn:aws:bedrock:...foundation-model/gpt-4o`-shaped ARN for the new OpenAI entry had it
not been filtered by `provider == "bedrock"` first. Caught and fixed alongside a
regression test (`test_bedrock_iam_resources_never_include_a_non_bedrock_catalogue_entry`)
specifically because the existing "not a wildcard" tests would *not* have caught it — a
syntactically valid-looking but semantically wrong ARN passes those checks fine.

`infrastructure/lambda_requirements.txt` and `pyproject.toml`'s `dependencies` are two
separately-maintained lists that must list `openai` identically — a real drift risk
`docs/guides/developer-guide.md` and `docs/guides/model-onboarding-guide.md` now call out
explicitly.

## Consequences
* **A new trust boundary**: every prior request stayed entirely within AWS (client →
  API Gateway → Lambda → Bedrock, all AWS-to-AWS). A request routed to an OpenAI-provider
  model now sends prompt content to a third-party service over the public internet — see
  `docs/security/threat-model.md`'s new T23 for the specific risk this introduces and its
  mitigation.
* Cost estimation, structured logging, and EMF metrics needed **zero changes** — they
  were already provider-agnostic (`EstimatedCost` is a pure function of `Usage` and
  catalogue `ModelPricing`; the EMF/log field whitelists were never Bedrock-specific).
  `docs/cost/cost-comparison-report.md` now includes `balanced-text-openai` automatically
  the next time `scripts/cost_comparison_report.py` runs, since it reads the live
  catalogue rather than a hardcoded model list.
* A real, working example ships alongside the mechanism, not just unit tests:
  `policies/applications/multi-provider-demo.yaml` configures `balanced-text-primary`
  (Bedrock) as preferred with `balanced-text-openai` (OpenAI) as fallback — a single
  fallback chain spanning two providers. `scripts/run_demo_scenarios.py --scenario
  multi-provider-fallback` exercises it end to end with fakes;
  `scripts/openai_live_smoke_test.py` (opt-in, cost-gated, never run by CI, mirroring
  `bedrock_live_smoke_test.py`) exercises it for real.
* `ProviderName.OPENAI` and `ModelResolutionType`'s existing values are reused as-is —
  no new resolution type was needed since `direct_model_id` (an OpenAI model name, not a
  Bedrock model ID) and `router_alias` both already generalize cleanly.

## Alternatives considered
* **A second AWS-native option** (e.g. treating a different Bedrock model family as a
  second "provider") — rejected: doesn't actually test ADR-002's claim, since it never
  leaves Bedrock's Converse API and IAM/credential model at all.
* **Azure OpenAI, Anthropic's direct API, or Google Vertex AI** — plausible alternatives,
  not rejected on technical merit; OpenAI was chosen for being the most broadly
  recognizable non-AWS vendor for a portfolio reviewer, and for having a real,
  well-documented Python SDK with a typed exception hierarchy that maps cleanly onto this
  project's existing `ProviderErrorCategory` taxonomy. Nothing in `CompositeModelProvider`
  or `adapters/common/` is OpenAI-specific — a third provider follows the same pattern.
* **Bundling retry/model-resolution logic separately per adapter instead of extracting
  `adapters/common/`** — rejected: would have meant copy-pasting `BedrockModelProvider`'s
  catalogue-resolution and retry logic verbatim into `OpenAIModelProvider`, immediately
  risking the two drifting apart on behavior that has nothing to do with either
  provider's actual wire format.
