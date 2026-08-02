# Requirements

This document enumerates the functional and non-functional requirements for
`aws-model-router`. It is the reference used to judge whether a phase's deliverables are
complete, and is expected to evolve as later phases add detail (particularly security,
observability, and cost requirements in Phases 6–7).

## Functional requirements

### FR-1 — Centralized request intake

FR-1.1. Applications submit inference requests to the router; they do not call Amazon
Bedrock (or any other model provider) directly.

FR-1.2. The router accepts a normalized request containing an application identity, a
message list (or prompt), a set of routing requirements, and optional metadata
(conversation ID, idempotency key, use case).

FR-1.3. The router validates and normalizes every request before any routing decision is
made. Malformed requests are rejected with a structured error and never reach the
routing or invocation stages.

### FR-2 — Policy-driven routing

FR-2.1. Each application has a routing policy that determines which logical capabilities,
quality tiers, models, and cost/token limits it may use. Client-supplied requirements are
constraints to satisfy, not instructions the router blindly obeys — the effective request
is the intersection of what the client asked for and what the application's policy
permits.

FR-2.2. The router resolves eligible model candidates by filtering on: capability match,
model allowlist membership, token limits, and estimated cost limits.

FR-2.3. The router scores and selects among eligible candidates using a documented,
deterministic routing strategy (see `docs/adr/0007-deterministic-explainable-routing.md`).

FR-2.4. Every routing decision carries one or more stable, machine-readable reason codes
explaining why a route was selected, and why alternatives were not.

### FR-3 — Model invocation

FR-3.1. The router invokes the selected model through a provider-independent
`ModelProvider` interface; Amazon Bedrock (via the Converse API) is the first
implementation, OpenAI (via the Chat Completions API) is the second
([ADR-029](adr/0029-multi-provider-routing-openai.md), Phase 10a). A
`CompositeModelProvider` dispatches each request to the correct concrete adapter based
on the catalogued model's `provider` field — this dispatch is itself just another
`ModelProvider` implementation from the application layer's point of view, so this
requirement holds regardless of how many providers are actually registered.

FR-3.2. Clients cannot submit raw provider model IDs. They request logical capabilities;
trusted, server-side configuration resolves capabilities to specific model aliases,
model IDs, or inference profiles.

FR-3.3. The router normalizes provider-specific responses (content, stop reason, token
usage) into a stable internal response shape, independent of which provider served the
request.

### FR-4 — Fallback

FR-4.1. When the primary model invocation fails with an eligible, retryable failure
(throttling, transient provider error, eligible timeout), the router selects an approved
fallback per the application's fallback policy.

FR-4.2. Fallback does not occur for validation failures, authorization/authentication
failures, policy denials, cost-limit rejections, unsupported-capability rejections, or
malformed configuration.

FR-4.3. Retries and fallback attempts are bounded (maximum attempts, retry budget) to
prevent retry/cost amplification.

FR-4.4. Fallback also applies when the preferred model is excluded *before* invocation
is attempted (e.g. by sustained model-health degradation), not only when it fails
*during* invocation — an eligible, policy-approved fallback model must still be tried in
either case (see
[ADR-028](adr/0028-fallback-chain-considers-health-excluded-candidates.md), added in
Phase 9 after fault-injection testing found the original implementation only covered the
invocation-time-failure case).

### FR-5 — Experimentation

FR-5.1. The router supports deterministic, weighted experiment routing: a stable subject
key (e.g. application + conversation, or an explicit experiment key) is hashed to assign
a consistent cohort across repeated calls.

FR-5.2. Experiment allocation is explainable — the routing decision records which
experiment (if any) influenced route selection.

### FR-6 — Idempotency

FR-6.1. Clients may supply an idempotency key. Given the same application, idempotency
key, and normalized request, the router must not perform unbounded duplicate model
invocations.

FR-6.2. Whether a cached response may be returned for a repeated idempotent request is a
policy decision per application, not a default behavior (see
`docs/adr/0008-metadata-only-audit-records-by-default.md` and the idempotency ADR added in
Phase 4).

### FR-7 — Auditability

FR-7.1. Every routing decision and invocation attempt is recorded as sanitized,
structured metadata (not raw prompts/responses) sufficient to explain what happened,
when, and why.

FR-7.2. Authorized callers can retrieve a sanitized routing decision by ID
(`GET /v1/decisions/{decisionId}`).

### FR-8 — Explainability without disclosure

FR-8.1. The router can explain why a route was selected (reason codes, evaluated
candidates, policy version) without exposing internal secrets, credentials, or
unrestricted provider configuration.

### FR-9 — Route evaluation without invocation

FR-9.1. Clients (or operators) can evaluate what route would be selected for a given
request without invoking a model, via `POST /v1/routes/evaluate`.

### FR-10 — Capability discovery

FR-10.1. Clients can discover the logical capabilities and service tiers available to
them via `GET /v1/models`, without seeing raw provider model IDs or unrelated
applications' configuration.

## Non-functional requirements

### NFR-1 — Cost

NFR-1.1. The default deployment uses only pay-per-request billing (Lambda, API Gateway,
DynamoDB on-demand, Bedrock on-demand). No resource incurs cost while idle beyond storage
and negligible fixed charges (e.g. CloudWatch Logs storage under retention limits).

NFR-1.2. No EC2, ECS, EKS, OpenSearch, Aurora, ElastiCache, NAT Gateway, or provisioned
Bedrock throughput is used in the base architecture.

NFR-1.3. All cost figures produced by the router (estimated cost) are explicitly labeled
as estimates and are never presented as equivalent to AWS billing — see
[`docs/cost/cost-estimation-guide.md`](cost/cost-estimation-guide.md) for the full
estimate-vs-billing gap explanation.

### NFR-2 — Security

NFR-2.1. Clients cannot select arbitrary provider model IDs; only trusted, policy-resolved
aliases — an unrecognized request field is never read by the request-mapping layer, so
it cannot influence which model is invoked (see
[`docs/security/threat-model.md`](security/threat-model.md)'s T5).

NFR-2.2. All AWS resources follow least-privilege IAM; Lambda execution roles are scoped
to the specific resources and, where feasible, specific model/inference-profile ARNs they
require — reviewed and tightened to the exact DynamoDB actions each adapter uses (see
[ADR-022](adr/0022-least-privilege-iam-review.md)).

NFR-2.3. Authentication is not based on API keys as a primary identity mechanism —
clients authenticate via IAM SigV4 (see
[ADR-015](adr/0015-api-authorization-model.md), and
[`docs/security/threat-model.md`](security/threat-model.md)'s T2 for this model's one
documented open gap: IAM proves identity, not a binding to a specific `applicationId`).

NFR-2.4. No raw prompt or response content is logged or persisted by default — verified
end to end by an abuse-case test (`tests/unit/handlers/test_abuse_cases.py`), not just
by convention.

See [`docs/security/threat-model.md`](security/threat-model.md) for the full threat
enumeration these requirements defend against, and
[`docs/security/security-architecture.md`](security/security-architecture.md) for the
layer-by-layer narrative (Phase 7).

### NFR-3 — Reliability

NFR-3.1. Bounded retries and bounded fallback prevent unbounded retry/cost amplification
during provider incidents.

NFR-3.2. The router degrades predictably: when no eligible model exists, it returns a
clear, typed error (`NO_ELIGIBLE_MODEL`) rather than an ambiguous failure.

NFR-3.3. Region-level resilience mechanisms (cross-Region inference profiles) are
evaluated and documented, including their data-residency, IAM, and cost trade-offs, even
where not adopted in the base deployment (see
[ADR-023](adr/0023-cross-region-inference-profile-resilience.md)).

### NFR-4 — Observability

NFR-4.1. All logs are structured JSON with a fixed, documented set of safe attributes —
`src/shared/structured_logging.py`'s `JsonFormatter`; the fixed attribute list is
documented in `docs/operations/observability.md` (ADR-019).

NFR-4.2. Metrics use low-cardinality dimensions only; request/decision/user/conversation
IDs are never used as metric dimensions — every custom metric declares exactly one
CloudWatch dimension (`Environment`), enforced by `EmfMetricsPublisher._put_metric`
raising on any other property (ADR-019; `docs/operations/observability.md`).

NFR-4.3. Individual routing decisions can be published as events for external
subscribers, and traced as distributed spans, without either mechanism ever carrying raw
prompt/response content — `EventBridgeDecisionEventPublisher` (ADR-030) and OpenTelemetry
span attributes (ADR-031) both apply the same sanitized-metadata discipline as NFR-4.1's
structured logs (Phase 10b).

### NFR-5 — Testability

NFR-5.1. The domain and application layers are testable without AWS credentials, a
network connection, or a live provider endpoint (Bedrock or OpenAI).

NFR-5.2. Provider adapters are tested with fakes, `botocore.stub.Stubber` (Bedrock), or
real SDK response/exception types constructed directly (OpenAI, ADR-029 — the `openai`
package has no equivalent public stubber); any test requiring a real network call to a
provider is explicitly opt-in and excluded from CI.

### NFR-6 — Extensibility

NFR-6.1. A new model provider can be added by implementing the `ModelProvider` interface,
without changes to the core routing domain logic. **Verified, not just designed for**:
`OpenAIModelProvider` (Phase 10a, ADR-029) was added with zero changes to `src/domain/`
or `src/application/`.

NFR-6.2. Model capabilities (token limits, tool use, structured output, streaming,
modalities) are explicit, per-model configuration — never assumed uniform across models.

### NFR-7 — Determinism and explainability

NFR-7.1. Given the same request, policy, and model health/configuration snapshot, routing
decisions are deterministic and reproducible.

NFR-7.2. The base implementation does not use opaque machine-learning-based routing;
routing strategies are deterministic and their reasoning is enumerable via reason codes.

### NFR-8 — Operability

NFR-8.1. The system can be deployed and torn down entirely via documented commands
(CDK deploy / destroy), with no manual, undocumented console steps required.

NFR-8.2. Development and production environments are isolated (separate stacks,
configuration, and IAM roles).

NFR-8.3. Automated deployment authenticates to AWS via GitHub OIDC — no long-lived AWS
access keys are stored as GitHub secrets (see
[ADR-025](adr/0025-github-oidc-deploy-role-design.md)). Pull-request validation and
deployment are separate workflows with disjoint triggers, so a fork PR has no path to
deployment credentials (see [ADR-026](adr/0026-pr-and-deploy-workflow-separation.md)).
The one-time manual bootstrap this depends on (the OIDC trust itself, and repository
Environment/branch-protection configuration) is fully documented, not undocumented
console steps — see [`docs/operations/ci-cd.md`](operations/ci-cd.md).
