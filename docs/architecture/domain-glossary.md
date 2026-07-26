# Domain Glossary

This glossary defines the core domain vocabulary for `aws-model-router`. These terms are
implemented as typed models in `src/domain/` starting in Phase 2. Naming here is
authoritative — code, API contracts, and documentation should all use these terms
consistently.

## Core request/response models

**InferenceRequest** — The normalized, validated representation of a client's inference
request: application identity, messages, routing requirements, and optional metadata
(conversation ID, idempotency key). Produced by request validation; everything
downstream operates on this type, never on the raw HTTP payload.

**Message** — A single turn in a conversation: a `role` (`user`, `assistant`, `system`)
and `content`. A list of messages forms the conversation passed to the model.

**InferenceResponse** — The normalized response returned to the client: the model's
reply, the routing decision summary, usage/cost, and a request ID. Never contains raw
provider-specific fields.

**RoutingRequirements** — The caller's *requested* constraints (capability, quality
tier, latency preference, cost/token limits, tool-use/structured-output needs). Treated
as a request to satisfy, not an authoritative instruction — see **RoutingPolicy**.

**ApplicationIdentity** — The authenticated identity of the calling application,
resolved during authentication/authorization. Drives which `RoutingPolicy` applies.

## Policy and configuration models

**RoutingPolicy** — The server-side, versioned configuration that governs what an
application may do: allowed capabilities, allowed model aliases, quality tiers, cost and
token limits, fallback policy, and experiment configuration. The effective constraints
applied to a request are the intersection of `RoutingRequirements` and the applicable
`RoutingPolicy`.

**FallbackPolicy** — An ordered list of approved alternative model aliases for a given
primary route, plus the maximum number of attempts and the failure categories that are
eligible for fallback.

**ExperimentPolicy** — Configuration for deterministic, weighted experiment routing: an
experiment ID, candidate arms with weights, and the subject-key strategy used for stable
cohort hashing (e.g. `applicationId + conversationId`).

## Model catalogue models

**ModelDefinition** — A catalogued, routable unit: a logical model alias plus its
resolution (direct model ID, cross-Region inference profile, or application inference
profile), its `ModelCapabilities`, `ModelPricing`, and `ModelHealth`.

**ModelCapabilities** — Explicit, per-model capability metadata: supported logical
capability tags, token limits, tool-use support, structured-output support, streaming
support, supported modalities, and system-prompt support. Never assumed uniform across
models.

**ModelPricing** — Versioned, configuration-driven pricing (cost per input/output token
or per unit) used solely to compute **EstimatedCost**. Never hardcoded in business logic;
never presented as equal to actual AWS billing.

**ModelHealth** — Operational health signal for a model (e.g. `HEALTHY`, `DEGRADED`,
`UNAVAILABLE`), used by routing strategies and fallback eligibility. Sourced from
observed invocation outcomes, not predictive modeling.

## Routing decision models

**RouteCandidate** — A `ModelDefinition` under consideration for a specific request,
carrying the reason codes that apply to it (why it's eligible or why it was excluded)
and its estimated cost/token usage for this request.

**RouteScore** — The numeric/ordinal score a `RoutingStrategy` assigns a `RouteCandidate`
when more than one candidate remains eligible (e.g. lowest-cost ranking).

**RoutingDecision** — The final, recorded outcome of routing a request: the selected
model alias, provider, whether fallback was used, the ordered reason codes, the policy
ID/version applied, and a unique `decisionId`. This is what `/v1/decisions/{decisionId}`
returns (sanitized).

**RoutingReasonCode** — A stable, machine-readable enum explaining a routing outcome.
See [Reason codes](#reason-codes) below. Reason codes are part of the public contract:
they must not be renamed or repurposed without a documented, versioned change.

## Provider abstraction models

**ProviderRequest** — The provider-agnostic request shape passed to a `ModelProvider`
implementation (messages, inference parameters, capability requirements). Adapters
translate this into a provider-specific call (e.g. Bedrock's `Converse` request shape).

**ProviderResponse** — The provider-agnostic normalized result returned by a
`ModelProvider`: content, stop reason, and token usage — independent of which provider
served the request.

**Usage** — Input/output token counts for a completed invocation.

**EstimatedCost** — A `Decimal`-typed, explicitly-labeled cost estimate derived from
`Usage` and `ModelPricing`. Never equated with billed cost (ADR and `docs/cost/`, from
Phase 6, document the gap explicitly).

**InvocationAttempt** — A single attempt to invoke a specific model for a specific
request: the model alias, outcome status (`SUCCEEDED`, `THROTTLED`, `TRANSIENT_ERROR`,
`NON_RETRYABLE_ERROR`, `TIMEOUT`), and latency. A `RoutingDecision` may reference one
(primary succeeded) or several (fallback occurred) `InvocationAttempt` records.

## Audit and error models

**AuditRecord** — The sanitized, persisted record combining a `RoutingDecision` and its
`InvocationAttempt`s for observability and the decisions API. Contains metadata only —
never raw prompt or response content by default (ADR-008).

**ErrorResponse** — The typed error contract returned to clients: `requestId`,
`errorCode`, a human-readable `message`, and (where applicable) `reasonCodes`. See
[`api-contracts.md`](api-contracts.md) for the full error taxonomy.

## Reason codes

Stable, machine-readable codes attached to `RouteCandidate`s and `RoutingDecision`s.
This set is established in Phase 1 and implemented starting in Phase 2; it may grow, but
existing codes are never repurposed.

| Reason code | Meaning |
|---|---|
| `CAPABILITY_MATCH` | The candidate provides the requested logical capability |
| `MODEL_ALLOWED` | The candidate is on the application's model allowlist |
| `MODEL_NOT_ALLOWED` | The candidate was excluded — not on the application's allowlist |
| `WITHIN_COST_LIMIT` | The candidate's estimated cost is within the applicable limit |
| `COST_LIMIT_EXCEEDED` | The candidate was excluded — estimated cost exceeds the limit |
| `TOKEN_LIMIT_EXCEEDED` | The candidate was excluded — request exceeds the model's token limit |
| `LOWEST_ESTIMATED_COST` | The candidate was selected as the lowest-cost eligible option |
| `LATENCY_PREFERENCE_MATCH` | The candidate matches the requested latency preference |
| `QUALITY_TIER_MATCH` | The candidate matches the requested/allowed quality tier |
| `REGION_POLICY_MATCH` | The candidate satisfies applicable Region/data-residency policy |
| `MODEL_UNHEALTHY` | The candidate was excluded — current health signal is unhealthy |
| `MODEL_THROTTLED` | An invocation attempt was throttled by the provider |
| `MODEL_UNAVAILABLE` | The candidate/provider was unavailable at invocation time |
| `FALLBACK_SELECTED` | This candidate was selected as an approved fallback |
| `EXPERIMENT_ROUTE_SELECTED` | This candidate was selected due to experiment cohort assignment |
| `NO_ELIGIBLE_MODEL` | No candidate remained eligible after filtering |
| `INVALID_ROUTING_POLICY` | The resolved policy failed validation |
| `REQUIRED_CAPABILITY_UNAVAILABLE` | No configured model provides the requested capability at all |

## Core interfaces (protocols)

Defined in the domain/application layers and implemented by adapters (Phase 2–4):

* **ModelProvider** — invokes a model given a `ProviderRequest`; returns a
  `ProviderResponse` or a typed `ProviderError` (Phase 3; `BedrockModelProvider`).
* **ModelCatalogue** — resolves logical capabilities/aliases to `ModelDefinition`s
  (Phase 2; `LocalFileModelCatalogue`).
* **RoutingPolicyRepository** — resolves the effective `RoutingPolicy` for an
  application (Phase 2; `LocalFileRoutingPolicyRepository`).
* **RoutingStrategy** — selects/scores among `RouteCandidate`s (Phase 2 preferred-model/
  lowest-cost/quality-tier; Phase 4 adds weighted-experiment).
* **CostEstimator** — computes `EstimatedCost` from `Usage`/token estimates and
  `ModelPricing` (Phase 2; `DefaultCostEstimator`).
* **TokenEstimator** — estimates input/output token counts for a request (Phase 2;
  `DefaultTokenEstimator`).
* **IdempotencyStore** — deduplicates concurrent invocations and, if policy allows,
  replays a completed result (Phase 4; `InMemoryIdempotencyStore`).
* **RoutingDecisionRepository** — persists/retrieves `AuditRecord`s (Phase 4;
  `InMemoryRoutingDecisionRepository`).
* **Clock** — supplies the current UTC time (testable, injectable; Phase 2).
* **IdentifierGenerator** — generates request/decision IDs (testable, injectable;
  Phase 2).

**ModelHealthRepository** and **MetricsPublisher** remain deferred to Phase 6, alongside
their first real implementation and consumer — see `PROJECT_PLAN.md`'s "Open
assumptions" section for why health filtering specifically is not yet wired in even
though `ModelHealth`/`MODEL_UNHEALTHY` are modeled in the schema.

## Related documents

* [`overview.md`](overview.md) — architecture and component diagrams
* [`api-contracts.md`](api-contracts.md) — API request/response contracts using these models
* [`../adr/`](../adr/) — decisions that shaped this vocabulary (see ADR-006, ADR-007, ADR-008)
