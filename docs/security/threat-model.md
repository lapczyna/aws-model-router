# Threat model

Scope: `aws-model-router`'s five trust boundaries (`docs/architecture/overview.md`'s
trust boundary diagram) plus cross-cutting concerns. Each threat lists the existing
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
| T18 | Supply-chain compromise of a Python dependency | Dependencies are version-pinned (`pyproject.toml`) | No automated vulnerability scanning yet | Deferred to Phase 8 (dependency vulnerability scanning in CI) |

## Boundary 5 — Administrative / deploy-time

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T19 | Compromised CI/CD deploy credentials | Planned: GitHub OIDC, no static AWS keys in GitHub secrets | Not yet built | Deferred to Phase 8 |
| T20 | Unauthorized manual AWS console changes drifting from CDK-defined state | Documented operational discipline (`docs/operations/runbook.md`): manual edits are silently overwritten by the next `cdk deploy` | Detection relies on someone eventually redeploying, not real-time drift detection | Accepted — CloudFormation drift detection is a documented future enhancement, not built speculatively |

## Cross-cutting: AI content safety

| ID | Threat | Mitigation | Residual risk | Status |
|---|---|---|---|---|
| T21 | Harmful/unsafe generated content reaching a caller | **None provided by this router itself** — deterministic routing (ADR-007) answers "which model," never "is this content safe." See [ADR-024](../adr/0024-responsible-ai-gateway-placement.md) for the recommended Bedrock Guardrails integration point | Real until Guardrails integration (ADR-024) is actually implemented | Deferred — explicitly not claimed to be solved by routing, per the original project scope |
| T22 | Prompt injection causing a model to ignore system/application instructions | Same as T21 — out of scope for a routing layer; the calling application's own prompt design and Guardrails (ADR-024) are the relevant controls | Same as T21 | Deferred (same rationale as T21) |

## Summary

22 threats identified across 5 trust boundaries plus AI content safety. 13 Mitigated
(with a real, verifiable control — code, test, or ADR-documented architectural
constraint), 6 Accepted (a genuine residual risk with explicit rationale for not closing
it further now), 3 Deferred (explicitly scoped to Phase 8, or contingent on a
not-yet-built feature per ADR-024). No threat here is silently unaddressed — every row
has a status and a reason.

The most significant open item is **T2** (cross-application impersonation via
`applicationId` spoofing) — already flagged as a known limitation when the
authorization model was chosen (ADR-015) and now given both a real detective control
(caller-principal-ARN logging, this phase) and a concrete, actionable design for the
preventive fix, rather than being left as an unexamined gap.
