# Threat model

Scope: `aws-model-router`'s six trust boundaries (`docs/architecture/overview.md`'s
trust boundary diagram, extended in Phase 10a — see Boundary 6) plus cross-cutting
concerns. Each threat lists the existing
mitigation (with ADR/code references), the residual risk, and a status:
**Mitigated** (a real, verified control exists), **Accepted** (a real risk, deliberately
not fully closed, with rationale), or **Deferred** (scoped to a specific future phase).
See [`security-architecture.md`](security-architecture.md) for the narrative
walkthrough and [`alarm-response.md`](../operations/alarm-response.md) /
[`incident-response.md`](../operations/incident-response.md) for what to do when a
threat here is actually observed.

## Boundary 1 — Client → API Gateway (untrusted → AWS account edge)

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T1 | Unauthenticated access to `/v1/*` business routes | IAM SigV4 authorization on every `/v1/*` method ([ADR-015](../adr/0015-api-authorization-model.md)) | None beyond standard AWS credential hygiene | Mitigated |
| T2 | **Cross-application impersonation**: a caller with valid `execute-api:Invoke` permission claims a different application's `applicationId` in the request body, receiving that application's policy/cost limits and reading its decisions/idempotency cache | IAM proves *authentication*, not a binding to a specific `applicationId` (documented limitation, ADR-015). Phase 7 adds a **detective** control: the caller's actual IAM principal ARN (`event.requestContext.identity.userArn`) is now logged (`caller_principal_arn`, `src/shared/structured_logging.py`) alongside the claimed `applicationId` on every request, so a mismatch pattern is auditable via Logs Insights even though it isn't blocked in real time | No real-time **preventive** control exists yet — see "Recommended enhancement" below | Accepted (with a new detective control this phase); full preventive fix deferred |
| T3 | Oversized request body (resource exhaustion) | `MAX_REQUEST_BODY_BYTES` checked and rejected (400) before any JSON parsing (`api_handler.py`) | None | Mitigated |
| T4 | Malformed/deeply-nested JSON (parser resource exhaustion) | Bounded by the same byte-size cap; Python's `json` module has its own recursion guard | A pathological payload just under the byte cap could still be expensive to parse; not separately rate-limited | Accepted — the byte cap bounds the worst case to a fixed, small size; see `tests/unit/handlers/test_abuse_cases.py` |
| T5 | Smuggling unexpected fields into a request (e.g. an attempted `modelId` override) | `handlers/request_mapping.py:parse_inference_request` extracts only the specific, named fields it recognizes (`applicationId`, `messages`, `requirements`, ...) directly from the raw dict — an unrecognized field is never read, so it can have no effect on the resulting `InferenceRequest` or on routing. This is allowlist-by-field-extraction, not a pydantic `extra="forbid"` rejection at the HTTP boundary (that only guards the internal domain models' own constructors, which never see the raw, unfiltered request body) — verified by an abuse-case test asserting the field is absent from the parsed request and has zero effect on the outcome | An unrecognized field is silently ignored rather than rejected with `400` — a caller gets no feedback that a field they sent was meaningless. Not a security gap (it cannot influence anything), but a minor API-usability gap | Mitigated (corrected during Phase 7: this was initially miswritten as `extra="forbid"` rejection — verifying it with a real test caught the inaccuracy before it shipped) |
| T6 | Traffic flooding / denial-of-wallet | API Gateway stage throttling + Lambda reserved concurrency, both `EnvironmentConfig`-driven ([Phase 5]) | No per-application quota — throttling is account/stage-wide, not per-caller | Accepted — a per-application usage-plan enhancement is a documented future improvement, not built speculatively |
| T7 | Browser-based CSRF/CORS abuse | Not applicable — this is a server-to-server SigV4 API with no browser session/cookie model; no CORS configuration exists | None | Accepted (documented assumption: callers are backend services, not browsers) |

**Recommended enhancement for T2** (not built — a scoped, actionable design, not a
speculative implementation): add an optional `allowed_caller_principal_arns:
tuple[str, ...] | None` field to `RoutingPolicy`; when set, `api_handler.py` compares
`event.requestContext.identity.userArn` against it and returns `403 POLICY_DENIED` on a
mismatch. Left `None` (default) preserves today's behavior for every existing policy —
an explicit, backward-compatible opt-in, matching how every other Phase 6/7 addition in
this project defaults to off. Not implemented in Phase 7 because it requires a new
policy schema field, migration of `policies/applications/*.yaml` for any application
that wants to adopt it, and dedicated tests beyond this phase's scope — flagged here as
the next concrete step, not deferred without a plan.

## Boundary 2 — API Gateway → Lambda (edge → router execution environment)

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T8 | Lambda execution role privilege escalation via over-broad IAM | Explicit, minimal DynamoDB action grants and catalogue-scoped Bedrock ARNs ([ADR-022](../adr/0022-least-privilege-iam-review.md), ADR-017) | X-Ray tracing actions (`PutTraceSegments`/`PutTelemetryRecords`) remain `Resource: "*"` — AWS defines no resource-level permission for them | Mitigated (X-Ray wildcard reviewed and accepted, not overlooked) |
| T9 | Unhandled exception leaking internal details (stack traces, config paths) to the caller | `error_mapping.py` returns a fixed, sanitized `ErrorResponse` for every exception type; the original exception is only ever logged server-side | None found in testing | Mitigated |
| T10 | Raw prompt/response content leaking via logs or persisted audit records | Metadata-only audit records (ADR-008); structured-logging attribute whitelist excludes any message-content field (ADR-019) | None found — verified end-to-end by an abuse-case test asserting request content never appears in `AuditRecord` or any log line | Mitigated |
| T11 | Cold-start configuration-load failure causing silently degraded service | A failed catalogue/policy load fails Lambda initialization entirely — no request (including `/health`/`/ready`) is served by that execution environment; `LambdaErrorsAlarm` (Phase 6) fires on the resulting invocation errors | Detection is via the general error alarm, not a dedicated "config load failed" signal | Accepted — a dedicated cold-start-failure metric is a documented future observability enhancement |

## Boundary 3 — Trusted configuration (`policies/`)

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T12 | Unauthorized or unreviewed routing-policy/catalogue tampering | Configuration is version-controlled YAML bundled into the Lambda deployment package — changing it requires a code change, review, and `cdk deploy` (ADR-010); no runtime write path exists | Repository/branch-protection hygiene (who can merge to `main`) is outside this project's own controls | Accepted — standard source-control governance, not a router-specific control |
| T13 | Pricing manipulation to misrepresent estimated cost | `Decimal`-typed, versioned pricing (`ModelPricing.pricing_version`); estimates are never presented as billed cost (ADR-005) | None — a deliberately wrong `pricing_version` bump is a config-review problem, not an application-security one | Mitigated |

## Boundary 4 — AWS managed services (Bedrock, DynamoDB, CloudWatch)

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T14 | Idempotency key collision/replay across applications | Idempotency records are keyed by `(application_id, idempotency_key)` — collision requires knowing another application's exact key *and* successfully claiming its `applicationId` (see T2) | Inherits T2's residual risk; does not introduce a new one | Mitigated (conditional on T2's status) |
| T15 | Retry/fallback cost amplification during a provider incident | Bounded ceiling: `FallbackPolicy.maximum_attempts × RetryPolicy.max_attempts` (ADR-014), never open-ended | None — the ceiling is fixed and tested | Mitigated |
| T16 | DynamoDB data tampering via over-broad IAM | Explicit minimal action grants, no `Scan`/`Query`/`UpdateItem` (ADR-022) | None found | Mitigated |
| T17 | Cross-tenant decision access (`GET /v1/decisions/{decisionId}`) | `applicationId` ownership check (`handle_get_decision`, tested — wrong owner → `403`) | Inherits T2's residual risk (the check compares against the *claimed* `applicationId`, not a verified IAM-bound one) | Mitigated (conditional on T2's status) |
| T18 | Supply-chain compromise of a Python dependency | Version-pinned (`pyproject.toml`) plus automated scanning: `pip-audit` runs as a required PR check (`.github/workflows/pr.yml`), and Dependabot proposes version-bump PRs weekly (`.github/dependabot.yml`) | A small, tracked set of dev-tooling-only advisories (black/pytest, no fix available inside this project's current version pin) are explicitly ignored with inline justification, not silently — see `docs/operations/ci-cd.md` | Mitigated |

## Boundary 5 — Administrative / deploy-time

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T19 | Compromised CI/CD deploy credentials | GitHub OIDC, no static AWS keys in GitHub secrets ([ADR-025](../adr/0025-github-oidc-deploy-role-design.md)); the GitHub-trusted role itself only grants `sts:AssumeRole` on the CDK bootstrap roles, never broad permissions directly; PR validation and deployment are separate workflows with disjoint triggers, so a fork PR has no path to any deploy credential at all ([ADR-026](../adr/0026-pr-and-deploy-workflow-separation.md)) | A compromised `main`-branch push (e.g. a maintainer's own compromised account) still reaches `deploy-dev` automatically — `prod` requires a separate human approval (the Environment's required-reviewers rule) | Mitigated |
| T20 | Unauthorized manual AWS console changes drifting from CDK-defined state | Documented operational discipline (`docs/operations/runbook.md`): manual edits are silently overwritten by the next `cdk deploy` | Detection relies on someone eventually redeploying, not real-time drift detection | Accepted — CloudFormation drift detection is a documented future enhancement, not built speculatively |

## Boundary 6 — Router → third-party model provider (OpenAI, ADR-029)

Every threat above assumes an all-AWS request path (client → API Gateway → Lambda →
Bedrock). Phase 10a's second provider (OpenAI) is the first time that stops being
universally true: a request routed to an `openai`-provider catalogue entry sends prompt
content to a third-party service over the public internet, not another AWS service
inside AWS's network boundary.

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T23 | Prompt/response content leaving the AWS trust boundary entirely when routed to an OpenAI-provider model | TLS in transit (the `openai` SDK's default HTTPS transport); routing to an `openai`-provider model is strictly opt-in per `RoutingPolicy.allowed_model_aliases` — an application never reaches OpenAI unless its policy explicitly allowlists an `openai` catalogue entry, and `policies/applications/multi-provider-demo.yaml` is the only sample policy that does | This project has no control over OpenAI's own data retention/training-use policy for content it receives — that is a vendor agreement/configuration concern (e.g. OpenAI's API data-usage settings), outside this router's own trust boundary and this ADR's scope | Accepted — inherent to offering a non-AWS provider at all, not a gap to close without removing the feature; an operator who cannot accept this should simply not allowlist an `openai` model for that application |
| T24 | OpenAI API key compromise or leakage | Stored in a dedicated Secrets Manager secret, never a Lambda plaintext env var value ([ADR-029](../adr/0029-multi-provider-routing-openai.md)); `secretsmanager:GetSecretValue` scoped to that one secret's ARN via `Secret.grant_read()`, never a wildcard (verified: `test_openai_secret_grant_is_scoped_to_the_specific_secret_not_wildcard`); the key is fetched once per cold start and only ever passed in-memory to the `openai.OpenAI(...)` client constructor — never logged (the structured-logging attribute whitelist has no field for it, so a call site couldn't log it even by mistake) | No automatic rotation — OpenAI has no rotate-in-place API for Secrets Manager's native rotation Lambdas to call against, so rotation is a manual, documented operational step (`docs/operations/release-process.md`), not an automated one | Mitigated (rotation is manual by necessity, not oversight — see the `AwsSolutions-SMG4` suppression in `infrastructure/cdk_constructs/lambda_construct.py`) |

## Cross-cutting: AI content safety

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T21 | Harmful/unsafe generated content reaching a caller | **None provided by this router itself** — deterministic routing (ADR-007) answers "which model," never "is this content safe." See [ADR-024](../adr/0024-responsible-ai-gateway-placement.md) for the recommended Bedrock Guardrails integration point | Real until Guardrails integration (ADR-024) is actually implemented | Deferred — explicitly not claimed to be solved by routing, per the original project scope |
| T22 | Prompt injection causing a model to ignore system/application instructions | Same as T21 — out of scope for a routing layer; the calling application's own prompt design and Guardrails (ADR-024) are the relevant controls | Same as T21 | Deferred (same rationale as T21) |

## Summary

24 threats identified across 6 trust boundaries plus AI content safety (T23/T24 added
Phase 10a for the new router-to-OpenAI boundary). 14 Mitigated (with a real, verifiable
control — code, test, or ADR-documented architectural constraint), 8 Accepted (a genuine
residual risk with explicit rationale for not closing it further now), 2 Deferred
(T21/T22, contingent on the not-yet-built Guardrails integration per ADR-024). No threat
here is silently unaddressed — every row has a status and a reason.

The most significant open item is **T2** (cross-application impersonation via
`applicationId` spoofing) — already flagged as a known limitation when the
authorization model was chosen (ADR-015) and now given both a real detective control
(caller-principal-ARN logging, this phase) and a concrete, actionable design for the
preventive fix, rather than being left as an unexamined gap.
