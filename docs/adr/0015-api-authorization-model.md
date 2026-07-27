# ADR-015: API authorization model

## Status
Accepted

## Context
Phase 1 required choosing exactly one primary authorization model for the public API:
IAM (SigV4) authorization for service-to-service use, or an API Gateway JWT authorizer.
API keys were explicitly ruled out as a primary identity mechanism (`docs/requirements.md`
NFR-2.3). The router's callers are internal applications (backend services), not
end-user browsers or mobile clients — there is no interactive login flow, no end user
to redirect through an identity provider, and no requirement to support third-party
callers.

## Decision
Every `/v1/*` business route (`inference`, `routes/evaluate`, `models`,
`decisions/{decisionId}`) requires **IAM authorization** (API Gateway
`AuthorizationType.IAM`, i.e. SigV4-signed requests). `/health` and `/ready` are
intentionally public (`AuthorizationType.NONE`) — standard liveness/readiness
convention, and neither exposes anything sensitive.

IAM authorization proves *authentication* (the caller holds valid AWS credentials with
an IAM policy granting `execute-api:Invoke` on this API) and *coarse* authorization (only
principals explicitly granted that permission can call the API at all). It does **not**
bind a specific IAM principal to a specific `applicationId`. Fine-grained,
per-application authorization — which capabilities, models, and cost limits an
application may use — is enforced entirely by the router's own policy engine (Phases
2–4), keyed on the `applicationId` field the caller supplies in the request body, exactly
as `docs/architecture/api-contracts.md` already specified before this ADR.

This is a deliberate, documented simplification: this project does not implement a
mapping from "calling IAM principal" to "permitted applicationId claims." A calling
service with `execute-api:Invoke` permission could, in principle, claim any
`applicationId` in its request body and receive whatever policy that application is
configured with. Closing this gap — e.g. validating the caller's IAM principal (role
ARN, tags) against an explicit allowlist of applicationIds it may claim — is flagged as
a finding for the Phase 7 threat model ("cross-application data exposure",
"unauthorized decision access") rather than solved here.

## Consequences
* No Cognito User Pool, OIDC provider, or JWT issuer/verification logic is needed —
  keeps the base deployment simpler and at zero idle cost (ADR-005).
* Callers must sign requests with SigV4 (standard for any AWS SDK or the `requests`
  library with an auth helper); this is a natural fit for other AWS-hosted services
  calling this API, less natural for a browser-based client (not a goal — this project
  explicitly is not a chatbot UI).
* `GET /v1/decisions/{decisionId}`'s "does the caller own this decision" check
  necessarily compares the request's `applicationId` query parameter against the stored
  decision's `applicationId` — not the IAM principal — inheriting the same
  simplification.
* Should a future need arise for genuine per-application IAM binding (e.g. a dedicated
  IAM role per onboarded application, validated server-side), it can be added as a
  targeted enhancement to `src/handlers/api_handler.py`'s authorization logic without
  changing the API Gateway authorization model itself.

## Alternatives considered
* **API Gateway JWT authorizer** — rejected as the primary model: requires an identity
  provider (Cognito or a third-party OIDC issuer) purely to mint tokens for
  service-to-service calls that have no human user behind them, adding cost and
  operational surface for no corresponding benefit at this project's scale.
* **API keys with usage plans** — rejected as identity (per NFR-2.3): API Gateway API
  keys are explicitly not a trustworthy identity mechanism (easily shared/leaked, not
  cryptographically bound to a caller) and are only appropriate for coarse usage-plan
  quotas, which this project achieves via stage-level throttling instead (no API keys
  needed at all).
* **Building a full IAM-principal-to-applicationId binding now** — rejected for Phase 5
  scope: a real, multi-tenant-safe implementation needs design attention (Phase 7
  threat model) beyond "choose and document one primary authorization model," which is
  what this phase was scoped to do.
