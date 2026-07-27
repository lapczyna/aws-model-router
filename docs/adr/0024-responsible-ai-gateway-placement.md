# ADR-024: Responsible AI Gateway placement

## Status
Accepted

## Context
The original project scope asked for a documented relationship between this router and
a "Responsible AI Gateway" — a content-safety/moderation layer for generative AI
applications — discussing both possible orderings (in front of vs. behind this router)
and recommending one, while being explicit that routing alone does not provide AI
safety.

**A factual correction first**: there is no single canonical, official AWS project
named exactly `aws-responsible-ai-gateway` (verified by searching for it directly). The
real, current, first-party AWS building block for this concern is **Amazon Bedrock
Guardrails** — a native Bedrock feature (content filters for hate/insults/sexual/
violence/misconduct/prompt-attacks, denied topics, word filters, PII detection and
redaction, contextual grounding checks, and Automated Reasoning checks), applied either
as a parameter on an `InvokeModel`/`Converse` call or via the standalone
`ApplyGuardrail` API. AWS also publishes several community "AI gateway" sample
repositories (e.g. `sample-genai-gateway-with-guardrails`,
`sample-ai-gateway-for-amazon-bedrock`) that address a broader problem than this
project's scope: a general-purpose, multi-tenant, often multi-provider proxy with
guardrail integration built in. This ADR evaluates the concept — a content-safety layer
alongside this router — grounded in what Bedrock Guardrails actually is, not a
specific named repository this project doesn't otherwise depend on.

## Decision
**Recommended ordering: guardrail checks integrated *into* the same Bedrock invocation
this router already makes — not a separate gateway service in front of or behind it.**

Two orderings were considered:

1. **In front of the router**: a separate edge component (API Gateway + Lambda, or one
   of the community AI-gateway samples) validates/moderates the raw client request
   before this router ever sees it.
2. **Integrated with the router's own invocation** (recommended): `BedrockModelProvider`
   passes a `guardrailIdentifier`/`guardrailVersion` on the same `Converse` API call it
   already makes (`domain.provider.ProviderRequest` gains an optional guardrail
   reference, resolved from `RoutingPolicy`/`ModelDefinition` configuration — the same
   configuration-driven pattern every other per-application setting in this project
   already uses). Bedrock itself checks both the input prompt and the generated
   response in that one call.

Recommendation rationale: option 2 matches how AWS actually designed Guardrails — a
parameter on the exact call this router's `BedrockModelProvider` already performs, not a
separate service call. It adds **zero new network hops, zero new components to deploy
and secure, and zero duplicated policy-resolution logic** — `RoutingPolicy` already
resolves per-application configuration (allowlists, cost limits); which guardrail
applies is exactly one more per-application/per-capability setting of the same shape.
Option 1 would require building a second policy-resolution system in the edge
component just to know which guardrail applies to which caller — logic this router
already has — and adds an operational component (and its own trust boundary, IAM role,
and failure mode) purely to re-derive information already available one layer in.

**This is a documented direction, not yet implemented.** No catalogue entry configures
a guardrail today, and `ProviderRequest`/`BedrockModelProvider` do not yet carry a
guardrail parameter — this ADR records the recommended integration point for when
content-safety requirements are actually prioritized, consistent with this project's
established pattern of not building undemonstrated-need features speculatively (ADR-020,
ADR-023).

**Explicitly, regardless of ordering**: this router's own routing/fallback/cost logic
provides *none* of the content-safety guarantees a guardrail provides. Deterministic,
explainable routing (ADR-007) answers "which model, and why" — never "is this content
safe." The two concerns are orthogonal and this project makes no claim, implicit or
explicit, that centralized routing is itself an AI-safety control.

## Consequences
* Adding real guardrail support later is additive: an optional field on
  `ModelDefinition`/`RoutingPolicy`, an optional parameter threaded through
  `ProviderRequest` → `BedrockModelProvider`, and Bedrock's own
  `GUARDRAIL_INTERVENED` stop reason surfaced through the existing normalized
  `StopReason` vocabulary (ADR-009) — no new architectural layer, no new ADR-level
  trust boundary.
* A guardrail intervention (blocked content) becomes a normal, explainable outcome in
  the existing reason-code/audit vocabulary, not a special case requiring new
  infrastructure — consistent with ADR-007/ADR-008.
* Choosing integration-over-separate-gateway means this router still does not attempt
  to be a general-purpose, multi-provider AI gateway (that is explicitly a different,
  broader class of project than this one, per `README.md`'s stated scope) — Guardrails
  integration stays scoped to what this router already invokes (Bedrock), not a
  provider-agnostic moderation layer.

## Alternatives considered
* **A separate Responsible AI Gateway component in front of this router** — rejected as
  the recommended default per the rationale above; still a legitimate choice for an
  organization that already operates a shared, multi-provider gateway across many
  applications beyond this router's scope, and wants content-safety policy centralized
  there instead of per-router-deployment. Documented as viable, not recommended for
  this project specifically.
* **Building or depending on one of the community AI-gateway sample repositories** —
  rejected: those samples solve a broader problem (general-purpose multi-tenant/
  multi-provider proxying) than this project's stated scope of a policy-driven *router*
  for a defined set of internal applications; adopting one would import scope and
  operational surface this project doesn't need.
* **No guardrail integration, ever** — rejected as a documented position: while not yet
  implemented, leaving this undecided would contradict the original scope's explicit
  requirement to document a recommendation.
