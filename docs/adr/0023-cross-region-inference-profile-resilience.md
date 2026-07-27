# ADR-023: Cross-Region inference profile resilience evaluation

## Status
Accepted

## Context
Phase 7's threat model and resilience review require evaluating cross-Region inference
profiles as an optional resilience mechanism against single-Region Bedrock capacity/
availability incidents. The domain/catalogue schema and IAM ARN builder already support
`ModelResolutionType.CROSS_REGION_INFERENCE_PROFILE` (`src/domain/enums.py`,
`infrastructure/cdk_constructs/lambda_construct.py`'s `_load_bedrock_resource_arns`)
since Phase 2/5, but every entry in the base `policies/model_catalogue.yaml` uses
`direct_model_id` — cross-Region profiles have never actually been exercised against a
real Bedrock invocation in this project.

## Decision
**Not adopted in the base deployment.** Cross-Region inference profiles remain an
available, opt-in `ModelResolutionType` an operator can choose per catalogue entry — the
base sample configuration stays on `direct_model_id` for predictability and simplicity.
This ADR documents the trade-offs an operator must weigh before adopting one, and one
concrete implementation gap that must be closed first.

**Resilience benefit**: a cross-Region inference profile lets Bedrock transparently route
an invocation to whichever Region (within the profile's geography, e.g. multiple US
Regions) has capacity, improving availability during a single-Region throttling/capacity
incident — complementary to, not a replacement for, this project's own
policy-controlled fallback (ADR-011), which operates at the *model* level, not the
*Region* level.

**Data-residency trade-off**: request/response data may be processed in any Region within
the profile's geography, not only the Region the Lambda itself runs in. For a
compliance-sensitive workload requiring processing to stay within a specific Region or
jurisdiction, this is disqualifying — `direct_model_id` (pinned to exactly the catalogue
entry's declared `region`) remains the only resolution type with that guarantee.

**IAM gap that must be closed before real adoption**: invoking a cross-Region inference
profile requires `bedrock:InvokeModel`/`Converse` permission on **both** the inference
profile ARN **and** every underlying regional foundation-model ARN the profile may route
to — not the inference-profile ARN alone. `_load_bedrock_resource_arns` today only adds
the inference-profile ARN for a `cross_region_inference_profile`/
`application_inference_profile` catalogue entry; it does not enumerate or grant the
underlying per-Region foundation-model ARNs. A catalogue entry switched to this
resolution type today would very likely fail with an IAM `AccessDenied` error at actual
invocation time — this has not been fixed speculatively, since doing so requires either
hardcoding each geography's Region list (a real, ongoing maintenance burden as AWS adds
Regions to a geography) or a synth-time Bedrock API call to resolve profile membership
(a new, deploy-time AWS dependency this project has otherwise avoided). Fixing this is
scoped to whichever future change actually adopts cross-Region profiles for a real
catalogue entry, not before.

**Cost consideration**: no separate cross-Region routing fee is charged; usage is metered
under whichever Region actually served each request, which complicates
per-Region cost attribution but not overall spend (see
`docs/cost/cost-estimation-guide.md`).

## Consequences
* Operators needing higher Bedrock availability than a single Region provides have a
  documented, available path (switch a catalogue entry's `resolution.type` to
  `cross_region_inference_profile`) — but must first extend
  `_load_bedrock_resource_arns` to grant the underlying regional ARNs, and confirm the
  chosen geography is acceptable for their data-residency requirements.
* The base deployment's resilience story stays exactly what Phases 4–6 already built:
  policy-controlled model-level fallback (ADR-011) and bounded retries (ADR-014) — both
  already real, tested, and Region-agnostic — rather than a Region-level mechanism that
  would currently fail if enabled.
* Revisit this ADR (update, don't silently abandon) if a future phase or real deployment
  need actually adopts cross-Region profiles — at minimum, `_load_bedrock_resource_arns`
  needs the underlying-ARN enhancement, and the CDK assertion tests
  (`tests/infra/test_model_router_stack.py`) need a case covering it.

## Alternatives considered
* **Adopt cross-Region profiles in the base catalogue now** — rejected: the IAM gap
  above means it would not actually work against real Bedrock without the ARN-builder
  enhancement, and building that speculatively (no catalogue entry uses it, no test could
  meaningfully exercise it against real Bedrock in this project's zero-live-AWS-call CI
  posture) would be exactly the kind of undemonstrated-need complexity this project
  avoids elsewhere (see ADR-020's `ModelHealthRepository` scope decision for the same
  reasoning pattern).
* **Global cross-Region inference profiles** (spanning multiple geographies, not just
  multiple Regions within one) — rejected for the same reasons, with an even larger
  data-residency implication; not evaluated further here.
