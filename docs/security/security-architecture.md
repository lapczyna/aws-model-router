# Security architecture guide

A narrative walkthrough of `aws-model-router`'s security posture, layer by layer,
following the client-request path. See [`threat-model.md`](threat-model.md) for the
full threat enumeration this architecture defends against, and
`docs/architecture/overview.md`'s trust boundary diagram for the visual reference this
guide narrates.

## Layer 1 — Network edge and authentication

Every `/v1/*` request must be SigV4-signed by an IAM principal holding
`execute-api:Invoke` on this API (ADR-015). There is no API key, no bearer token, no
interactive login — this is a deliberate choice for a service-to-service API with no
end user behind it (NFR-2.3). `/health` and `/ready` are the only unauthenticated
routes, by convention, and expose nothing sensitive.

API Gateway itself enforces this boundary — an unsigned or invalid request never
reaches the Lambda at all. This means the Lambda's own code never needs to implement
authentication logic, and a compromised or buggy handler cannot accidentally bypass it.

## Layer 2 — Request validation and size bounding

Before any business logic runs, `api_handler.py` rejects oversized bodies
(`MAX_REQUEST_BODY_BYTES`) and malformed JSON, both with a generic `400
INVALID_REQUEST` — never echoing the caller's own malformed input back to them.
`handlers/request_mapping.py:parse_inference_request` then extracts only the specific,
named fields it recognizes from the raw request dict — an unrecognized field (e.g. an
attempted raw model-ID override) is never read, so it cannot influence the resulting
`InferenceRequest` or anything downstream (ADR-006's "no client-supplied model IDs"
holds by construction: the routing engine never looks at a field it didn't ask for).
Every domain model (`InferenceRequest`, `RoutingRequirements`, etc.) separately uses
`extra="forbid"`, which guards against a bug in *this project's own code* ever
constructing one of these models from an unfiltered dict — it is not what protects
against a client-supplied extra field, since the client's raw body is never passed to a
domain model constructor directly.

## Layer 3 — Policy-driven authorization (the router's own engine)

Once past authentication, every routing decision is filtered through the caller's
`RoutingPolicy` — capability allowlists, model allowlists, quality tiers, cost limits,
token limits (Phase 2) — resolved by `application_id`, not by IAM principal (ADR-015's
documented simplification; see `threat-model.md`'s T2). This is a second, independent
authorization layer beneath IAM: even a caller with valid credentials cannot request a
capability, model, or cost the resolved policy doesn't permit — every such attempt is
recorded as an explicit, explainable reason code (ADR-007), not silently downgraded.

## Layer 4 — Execution environment (Lambda + IAM)

The Lambda execution role is scoped to exactly what the code calls:

* **Bedrock**: `InvokeModel`/`Converse`/`ConverseStream` on exactly the catalogued
  models'/inference-profiles' ARNs, computed at synth time from
  `policies/model_catalogue.yaml` (ADR-017) — never `resources=["*"]`.
* **DynamoDB**: `GetItem`/`PutItem` on the decisions table, `GetItem`/`PutItem`/
  `DeleteItem` on the idempotency table — never `Scan`, `Query`, or `UpdateItem`
  (ADR-022, Phase 7's least-privilege review).
* **CloudWatch Logs**: the standard basic-execution-role grant, scoped to this
  function's own log group.
* **X-Ray**: `PutTraceSegments`/`PutTelemetryRecords` with `Resource: "*"` — reviewed
  and accepted, since AWS defines no resource-level permission for either action
  (ADR-022).
* **Secrets Manager** (Phase 10a, ADR-029): `GetSecretValue` on exactly one secret — the
  OpenAI API key — via `Secret.grant_read()`, never a wildcard. Provisioned, and this
  grant added, only if `policies/model_catalogue.yaml` actually declares an `openai`
  model; a Bedrock-only deployment has no Secrets Manager permission on this role at all.

No permission here was added because "it might be useful" — every statement traces to
a specific, reviewed line of adapter code.

## Layer 5 — Data handling and audit

Persisted `AuditRecord`s and every structured log line contain metadata only — decision
IDs, model aliases, reason codes, latencies, cost estimates — never the raw prompt or
model response content (ADR-008). The structured-logging formatter enforces this with
an explicit field whitelist (`_ALLOWED_EXTRA_KEYS`, ADR-019): a call site cannot
accidentally log message content even by mistake, because any field not on the list is
silently dropped, not passed through.

DynamoDB items are AWS-managed-encrypted at rest, TTL-expired automatically, and (in
`prod`) point-in-time-recoverable (ADR-018). `prod` additionally retains data on stack
deletion (`RemovalPolicy.RETAIN`) — deliberately, so a `cdk destroy` cannot silently
discard the audit trail.

## Layer 6 — Observability as a security control

Structured logs and the `caller_principal_arn` field (Phase 7) turn the one open
authorization gap this project documents (T2 in the threat model — `applicationId`
spoofing) from an invisible risk into an auditable one: every request's actual IAM
identity is logged next to its claimed `applicationId`, queryable via CloudWatch Logs
Insights. This doesn't close the gap, but it means the gap is never silent.

## Layer 7 — Deployment-time security

The CDK deployment role (GitHub OIDC, ADR-025) is intentionally distinct from the
Lambda's runtime execution role — neither is a superset of the other. A compromised
runtime role cannot redeploy infrastructure; a compromised deploy role (scoped to CI,
not to any live request path, and itself only able to assume the CDK bootstrap roles —
never a broad permission directly) cannot serve a live request. Configuration changes
(`policies/`) require the same deploy path as any other code change — reviewed,
version-controlled, no separate unreviewed runtime mutation path exists (ADR-010).
PR validation and deployment are separate GitHub Actions workflows with disjoint
triggers (ADR-026), so a fork PR has no path to any deploy credential at all.

## What this architecture does not claim

Routing is deterministic and explainable (ADR-007) — it answers "which model was
chosen, and why," never "is this content safe." No layer above provides content
moderation, prompt-injection defense, or any other AI-safety guarantee; see
[ADR-024](../adr/0024-responsible-ai-gateway-placement.md) for where that concern is
recommended to integrate, and `threat-model.md`'s T21/T22 for why this project makes no
claim otherwise.
