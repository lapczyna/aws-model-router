# Project Plan

This document is the authoritative, living plan for `aws-model-router`. It exists so
development can resume coherently even if prior conversational/session context is lost.
It is updated at the end of every phase: milestones move from "remaining" to "completed",
and any scope adjustments discovered along the way are recorded here rather than only in
chat history.

## Project vision

Build a serverless, policy-driven model routing platform on AWS. Applications never
invoke foundation models directly — they send inference requests to a centralized Model
Router, which decides which approved model should handle each request based on
configurable policy (capabilities, use case, application identity, data classification,
allowlists, estimated cost, latency preference, quality tier, model health, regional
availability, token limits, fallback configuration, experimentation configuration, and
governance requirements).

The system initially routes to models available through Amazon Bedrock, but the
architecture stays extensible enough that another provider could be added later through
an adapter, without changing the core routing domain. The emphasis throughout is
architecture, policy-driven routing, cost control, reliability, observability, security,
testability, infrastructure as code, CI/CD, and operational maturity — not a chatbot UI.

Full functional/non-functional requirements: [`docs/requirements.md`](docs/requirements.md).
Architecture and diagrams: [`docs/architecture/overview.md`](docs/architecture/overview.md).

## Architectural principles

These hold across every phase; a change that violates one of these needs an ADR
justifying the exception, not a silent departure.

1. **Centralized enforcement.** Applications never call a model provider directly
   (ADR-001).
2. **Provider independence.** `src/domain/` has no AWS SDK imports; provider integration
   lives behind the `ModelProvider` interface in `src/adapters/` (ADR-002).
3. **No client-supplied model IDs.** Clients request logical capabilities; server-side
   configuration resolves aliases (ADR-006).
4. **Deterministic, explainable routing.** No opaque ML-based routing in the base
   project; every decision carries reason codes (ADR-007).
5. **Metadata-only audit by default.** No raw prompts/responses persisted unless a
   policy explicitly opts in (ADR-008).
6. **Pay-per-request only.** No always-on compute, no NAT Gateway, no provisioned
   throughput in the base deployment (ADR-005).
7. **Bounded retries and fallback.** Fallback is policy-controlled and never blind; retry
   and fallback attempts are capped to prevent cost/retry amplification.
8. **Configuration-driven, versioned pricing and policy.** Never hardcoded in business
   logic; costs are always labeled as estimates, never equated with billed cost.
9. **Thin handlers, testable core.** Lambda handlers parse/dispatch/format only; all
   business logic is unit-testable without AWS credentials.
10. **Least privilege everywhere.** IAM, model allowlists, and API authorization are
    scoped as tightly as the use case allows.

## How to use this document

* Each phase has a **Definition of Done (DoD)**. A phase is not complete until every DoD
  item is met.
* **Completed milestones** lists what phases have shipped, with the commit/tag that
  closed them (filled in once you confirm the commit/push for that phase).
* **Remaining milestones** is the backlog of phases not yet started.
* If you are picking this project back up cold: read this file top to bottom, then read
  the most recent ADRs in `docs/adr/`, then check `git log` against the "Completed
  milestones" table below to confirm reality matches this document. If they disagree,
  trust the repository and correct this file.

## Phase definitions and Definition of Done

### Phase 1 — Foundation and architecture
Repository structure, README, requirements, architecture docs and diagrams, API
contracts, domain glossary, roadmap, dev setup, coding standards, contribution guide,
security policy, PR/issue templates, `.gitignore`, `pyproject.toml` (Ruff/Black/mypy/
pytest config), pre-commit config, Makefile, ADR-001..010, this file.

**DoD:**
- [x] Repository structure matches `README.md#repository-structure`
- [x] All 10 initial ADRs present and cross-linked
- [x] `docs/requirements.md`, `docs/architecture/overview.md` (4 Mermaid diagrams),
      `docs/architecture/api-contracts.md`, `docs/architecture/domain-glossary.md` present
- [x] Tooling configs present (`pyproject.toml`, `.pre-commit-config.yaml`, `Makefile`)
- [x] No AWS infrastructure code, no Bedrock invocation code
- [x] Committed and pushed

### Phase 2 — Domain model and local routing engine
Typed domain models, routing policy schema, model catalogue schema, capability/allowlist/
token/cost filtering, deterministic preferred-model routing, lowest-estimated-cost
strategy, quality-tier strategy, stable reason codes, decision explanation, local JSON/
YAML configuration + validation, local CLI route evaluator, pricing as versioned
configuration (never hardcoded), comprehensive unit tests (see full list in the original
scope), all runnable without AWS credentials. No Bedrock calls, no AWS infrastructure.

**DoD:**
- [x] All domain models from `docs/architecture/domain-glossary.md` needed for routing
      (without invocation) implemented and typed — `ModelProvider`/`ProviderRequest`/
      `ProviderResponse`, `ModelHealthRepository`, `RoutingDecisionRepository`, and
      `MetricsPublisher` are deliberately deferred to the phase that first implements
      and consumes them (3, 4, 4, 6 respectively), rather than defined speculatively
      ahead of a caller
- [x] All three Phase 2 routing strategies (preferred-model, lowest-cost, quality-tier)
      implemented and unit-tested
- [x] CLI route evaluator (`scripts/evaluate_route.py`) runs with zero AWS
      credentials/network access
- [x] Reason codes reachable by Phase 2 logic are producible and asserted in tests:
      `CAPABILITY_MATCH`, `MODEL_ALLOWED`, `MODEL_NOT_ALLOWED`, `WITHIN_COST_LIMIT`,
      `COST_LIMIT_EXCEEDED`, `TOKEN_LIMIT_EXCEEDED`, `LOWEST_ESTIMATED_COST`,
      `QUALITY_TIER_MATCH`, `NO_ELIGIBLE_MODEL`, `REQUIRED_CAPABILITY_UNAVAILABLE` (10 of
      18). The remaining 8 — `LATENCY_PREFERENCE_MATCH`, `REGION_POLICY_MATCH`,
      `MODEL_UNHEALTHY`, `MODEL_THROTTLED`, `MODEL_UNAVAILABLE`, `FALLBACK_SELECTED`,
      `EXPERIMENT_ROUTE_SELECTED`, `INVALID_ROUTING_POLICY` — require health, provider
      invocation, fallback, or experiment logic that doesn't exist until Phases 3–4; the
      original wording of this DoD item ("every reason code") overstated Phase 2 scope
      and is corrected here rather than left misleading
- [x] `make ci` passes: Ruff, Black, mypy --strict, and pytest (83 tests, 98% coverage
      on `src/`) all clean
- [x] Committed and pushed

### Phase 3 — Bedrock provider adapter
`BedrockModelProvider` behind `ModelProvider`, Converse API request/response mapping,
configurable model IDs/inference profiles, token-usage extraction, stop-reason mapping,
provider error taxonomy, timeout handling, bounded retries with backoff+jitter,
throttling/transient/permanent error classification, safe error messages, logical
alias resolution. Tests via fakes and `botocore.stub.Stubber` only — no live Bedrock
calls in CI. Opt-in manual smoke-test script (env-flag gated, cost-warned, excluded from
CI, no prompt-content logging).

**DoD:**
- [x] `BedrockModelProvider` implements `ModelProvider` fully via Converse API —
      request/response mapping, stop-reason mapping, alias resolution (including a
      single-hop `ROUTER_ALIAS` indirection), pre-invocation capability validation
- [x] All listed failure modes covered by tests using fakes/Stubber: successful
      invocation, malformed response, throttling, transient failure, permanent failure,
      timeout, invalid model alias, missing usage information, unsupported parameter
      (capability) mapping, sanitized exceptions
- [x] No client path can reach an arbitrary model ID — `ProviderRequest.model_alias` is
      always resolved through the `ModelCatalogue`; an unknown alias is a `PERMANENT`
      `ProviderError` raised before any Bedrock call is attempted
- [x] Manual smoke-test script (`scripts/bedrock_live_smoke_test.py`) exists, requires
      an env flag + `--confirm-cost` + an explicit `--model-alias` (both gates verified
      to refuse execution without live AWS calls), and is excluded from CI (not a
      pytest module)
- [x] `make ci` passes with no live AWS calls: Ruff, Black, mypy --strict, pytest
      (148 tests — 65 new for Phase 3 — 98% coverage on `src/`, 100% on the new
      `adapters/bedrock/` package) all clean; contract tests use `botocore.stub.Stubber`
      against a real (but network-isolated) boto3 client
- [x] Committed and pushed

### Phase 4 — Fallback, experimentation, and idempotency
Explicit fallback policies + eligibility rules, max attempts/retry budget, deterministic
weighted experiment routing with stable cohort hashing, routing-decision persistence
interface, idempotency interface, concurrent duplicate-request strategy, invocation-
attempt records, final decision aggregation. New ADRs: fallback eligibility, deterministic
experimentation, idempotency strategy, retry/cost amplification controls.

**DoD:**
- [x] Fallback never triggers for the excluded failure categories — validation failure
      never reaches `InvocationOrchestrator` (rejected by `InferenceRequest` validation),
      policy denial/cost rejection/unsupported capability all manifest as
      `decision.selected_model_alias is None` before any invocation is attempted,
      malformed configuration propagates `ConfigurationError` unchanged, and a
      `PERMANENT` invocation failure stops the chain immediately (ADR-011). Authorization
      failure is not yet a domain concept (Phase 5).
- [x] Retry/fallback attempts are bounded (`FallbackPolicy.maximum_attempts`) and tested
      at the boundary (fallback-limit-enforced test)
- [x] Experiment cohort assignment is deterministic and boundary-tested (5000-sample
      allocation-proportion tests within tolerance, plus exact determinism assertions)
- [x] Idempotency covers repeated requests (cache hit, no re-invocation), concurrent
      duplicate requests (real `threading`-based test, not mocked), and expiry (both
      completed-record TTL and stale-in-progress-reservation recovery)
- [x] 4 new ADRs added (ADR-011..014)
- [x] `make ci` passes: Ruff, Black, mypy --strict, pytest (217 tests — 69 new for
      Phase 4 — 98% coverage on `src/`, 100% on all new Phase 4 modules) all clean
- [x] Committed and pushed

### Phase 5 — AWS CDK infrastructure and serverless API
CDK v2 Python stack (`ModelRouterStack`): API Gateway REST API (all 6 endpoints behind
one shared Lambda), DynamoDB (decisions + idempotency — *not* a config table; see the
"Open assumptions" note on ADR-010 below), CloudWatch Log Groups, least-privilege IAM,
a Lambda `live` alias, outputs, tags. One authorization model chosen (IAM) and recorded
as ADR-015. On-demand billing, TTL, encryption, PITR by environment, log retention,
throttling, request-size controls, reserved concurrency, environment-specific removal
policies, teardown support. CDK template/IAM/encryption/retention/public-access/
removal-policy/endpoint-authz assertion tests. No VPC for Lambda (no justified need);
no NAT Gateway.

**DoD:**
- [x] All 6 endpoints implemented behind a real, synthesizable CDK stack
      (`ModelRouterStack`) and verified end to end locally
      (`scripts/invoke_lambda_locally.py`, fake mode); "reachable in a dev environment"
      requires an actual `cdk deploy`, which is the user's action, not something this
      phase's automated verification performs (no AWS credentials were used) — see
      `docs/operations/deployment-and-teardown.md` for the deploy/verify steps
- [x] Authorization ADR recorded (ADR-015: IAM/SigV4) and enforced at the API Gateway
      method level (`AuthorizationType.IAM` on every `/v1/*` route; `NONE` on
      `/health`/`/ready`), verified by CDK template-assertion tests
- [x] CDK tests (`tests/infra/`, `pytest -m infra`, 24 tests) cover IAM least-privilege
      scoping (Bedrock + DynamoDB actions never resource `"*"`), encryption
      (`SSESpecification.SSEEnabled`), retention/PITR (environment-driven), removal
      policy (`dev`: `Delete`, `prod`: `Retain`), and endpoint authorization (public vs.
      IAM-protected routes) — against the real synthesized CloudFormation template, not
      just the construct source
- [x] `cdk destroy -c env=dev` fully tears down the dev environment with no orphaned
      resources (`RemovalPolicy.DESTROY` on both tables and both log groups); `prod`
      deliberately retains the two DynamoDB tables and log groups
      ([ADR-018](docs/adr/0018-dynamodb-decision-and-idempotency-store-design.md)) — this
      is documented as intentional, not a defect, in
      `docs/operations/deployment-and-teardown.md`
- [x] Committed and pushed

### Phase 6 — Observability, auditability, and cost governance
Structured JSON logs (sanitized metadata only), full custom metrics set, low-cardinality
dimensions only, CloudWatch dashboard, alarms (Lambda errors, API 5xx, provider failure,
fallback rate, no-eligible-model, throttling, estimated-spend guidance), operational
runbook, alarm-response guide, observability guide, cost-estimation guide. Application
inference profiles used where practical for cost attribution. Explicit documentation of
estimate-vs-billing gap, pricing update process, retry/fallback cost multiplication.

**DoD:**
- [ ] All listed metrics published with only approved dimensions
- [ ] No request/decision/user/conversation ID used as a metric dimension (verified)
- [ ] Dashboard + all listed alarms deployed
- [ ] Runbook, alarm-response guide, observability guide, cost guide written
- [ ] Committed and pushed

### Phase 7 — Security and resilience hardening
Threat model covering the full listed threat surface. Controls implemented/documented for
each. Cross-Region inference profiles evaluated as an optional resilience mechanism with
data-residency/IAM/cost trade-offs documented. `SECURITY.md` updates, threat model,
security architecture guide, incident-response guide, disaster recovery guide,
least-privilege IAM review, resilience test plan, abuse-case tests. Documented
relationship with `aws-responsible-ai-gateway` (both orderings discussed, one recommended
with justification) — explicitly not claiming routing alone provides AI safety.

**DoD:**
- [ ] Threat model document covers every listed threat category
- [ ] Every listed control is implemented or explicitly documented as out of scope with
      rationale
- [ ] Responsible AI Gateway placement documented with a recommendation
- [ ] Abuse-case tests added
- [ ] Committed and pushed

### Phase 8 — CI/CD with GitHub Actions
GitHub OIDC for AWS auth (no long-lived keys). PR workflow: install, Ruff, Black check,
mypy, unit tests, coverage, contract tests, policy-schema validation, CDK synth + CDK
tests, CFN lint, IaC security scan, dependency vulnerability scan, secret scanning.
Deployment workflow: manual/auto dev deploy per documented strategy, manual approval
gate before prod, separate GitHub environments + AWS roles, environment-specific CDK
context, CDK diff before deploy, deployment summary, smoke tests, rollback guidance.
Least-privilege deploy roles; fork PRs excluded from deployment permissions. Optional:
scheduled dependency checks, release creation, doc checks, pricing-freshness checks.
Branch-protection recommendations documented.

**DoD:**
- [ ] PR workflow runs and passes on a real PR, gating every listed check
- [ ] Deployment workflow deploys to dev and requires manual approval for prod
- [ ] OIDC trust policy documented; no static AWS keys in GitHub secrets
- [ ] Fork PRs verified to lack deployment permissions
- [ ] Committed and pushed

### Phase 9 — Performance, load testing, and portfolio polish
Contract tests, controlled load tests, fault injection (throttling/fallback/idempotency
concurrency simulation), routing benchmark, latency report, cost comparison report,
sample policies/catalogue, example requests/responses, troubleshooting/deployment/
developer/policy-authoring/model-onboarding/application-onboarding guides, release
process, final architecture review, future roadmap. The 10 sample demonstrations listed
in scope. Full repository self-review from 5 stated perspectives with high-priority
findings resolved. Portfolio section in README.

**DoD:**
- [ ] All 10 sample demonstrations reproducible via committed scripts/fixtures
- [ ] Load/fault-injection tests exist and pass
- [ ] Multi-perspective review completed; high-priority findings resolved or explicitly
      deferred with rationale
- [ ] Portfolio README section written
- [ ] Committed and pushed

### Phase 10 — Advanced extensions (optional, not started unless explicitly requested)
Bedrock Intelligent Prompt Router as an eligible route target, multi-provider routing,
streaming, tool-use/multimodal routing, quality feedback collection, offline evaluation,
contextual bandits, policy simulation, shadow routing, canary rollout, automatic health
scoring, EventBridge decision events, Step Functions approval flow, multi-account/tenant
isolation, OpenTelemetry, LLM eval platform integration, prompt caching policy,
quota-aware routing, carbon-aware routing research, governance evidence export. Any
adaptive/learning-based routing must start in shadow mode and never control production
traffic unvalidated.

## Completed milestones

| Phase | Status | Commit / tag |
|---|---|---|
| Phase 1 — Foundation and architecture | Complete | `b059a41` (+ `ee55487` username fix, `9210c11` plan update) |
| Phase 2 — Domain model and local routing engine | Complete | `771f98d` |
| Phase 3 — Bedrock provider adapter | Complete | `929ce7a` |
| Phase 4 — Fallback, experimentation, and idempotency | Complete | `324fe75` |
| Phase 5 — AWS CDK infrastructure and serverless API | Complete | `0b88448` |

## Remaining milestones

| Phase | Title |
|---|---|
| 6 | Observability, auditability, and cost governance |
| 7 | Security and resilience hardening |
| 8 | CI/CD with GitHub Actions |
| 9 | Performance, load testing, and portfolio polish |
| 10 | Advanced extensions (optional — explicit request only) |

## Open assumptions / decisions carried forward

These were made in Phase 1 to keep moving without blocking on the user; revisit if
incorrect:

* **License**: MIT. Change by editing `LICENSE` and the `license` field in
  `pyproject.toml` if a different license is preferred.
* **GitHub repository owner/URL**: confirmed as `lapczyna/aws-model-router` (matches the
  configured git remote), referenced in `.github/ISSUE_TEMPLATE/config.yml`.
* **Primary authorization model** (IAM vs. JWT authorizer) is explicitly deferred to
  Phase 5, per the original scope — not decided in Phase 1.
* **Package layout**: `src/domain`, `src/application`, `src/adapters`, `src/handlers`,
  `src/shared` are top-level installable packages (no shared umbrella package name),
  matching the repository structure specified for this project.
* **Domain model field casing**: internal Python domain models use `snake_case` field
  names (idiomatic Python, and required to avoid Ruff's `N815`/pep8-naming warnings on
  mixed-case attributes). The public HTTP API's `camelCase` JSON contract
  (`docs/architecture/api-contracts.md`) is a separate, external representation that a
  Lambda handler will translate to/from starting in Phase 5 — the two are not expected
  to share field names verbatim.
* **Deferred protocols**: `ModelProvider`/`ProviderRequest`/`ProviderResponse` were added
  in Phase 3; `IdempotencyStore` and `RoutingDecisionRepository` were added in Phase 4,
  as planned. `ModelHealthRepository` and `MetricsPublisher` remain deferred to
  Phase 6, alongside their first real implementation and consumer.
* **Health filtering**: model health (`ModelHealth`/`MODEL_UNHEALTHY`) is modeled in the
  catalogue schema (Phase 2) but still not wired into candidate filtering — Phase 4's
  explicit scope (fallback, experimentation, idempotency) did not include it, and no
  `ModelHealthRepository` exists yet to source a live signal from. This is now correctly
  deferred to Phase 6 (observability), where a real health signal — derived from
  invocation outcomes recorded as `InvocationAttempt`s — first becomes available to
  filter on. (An earlier note in this file said "Phase 4 scope"; corrected here now that
  Phase 4 is complete and didn't include it.)
* **Provider error taxonomy is category-based, not exception-subtype-based** (Phase 3):
  a single `domain.errors.ProviderError` carries a `category` attribute
  (`ProviderErrorCategory`: `THROTTLED`/`TRANSIENT`/`TIMEOUT`/`PERMANENT`) rather than a
  deep exception hierarchy. This lets Phase 4's fallback orchestrator make one decision
  (`category in {THROTTLED, TRANSIENT, TIMEOUT}` ⇒ retryable/fallback-eligible) without
  needing to catch multiple exception types.
* **Retry/backoff is full-jitter exponential**, with `attempt`, the `RetryPolicy`, and
  the jitter fraction all injectable — `BedrockModelProvider` never calls `random`/`time`
  directly in a way tests can't control, keeping retry tests deterministic and fast
  (no real sleeping).
* **Tool-use/structured-output invocation mechanics are out of scope through Phase 3**:
  `ProviderRequest.requires_tool_use`/`requires_structured_output` are used only as a
  pre-invocation capability check against `ModelCapabilities` (raising a `PERMANENT`
  `ProviderError` if unsupported) — actual Converse `toolConfig` request construction and
  tool-call response parsing is explicitly Phase 10 scope ("tool-use capability
  routing"), per the original project scope.
* **`ROUTER_ALIAS` resolution is a single, bounded hop**: `BedrockModelProvider` resolves
  one level of indirection (a router alias pointing at another catalogue entry) and
  rejects a router alias pointing at another router alias as a configuration error,
  rather than following an arbitrary/recursive chain.
* **`RoutingStrategy.select()` gained a `context: RoutingContext` parameter** (Phase 4):
  `ExperimentStrategy` needs `application_id`/`conversation_id` to build a cohort subject
  key, which the original Phase 2 signature (`eligible`, `policy`, `requirements`) had no
  way to supply. A small dataclass (not more loose parameters) was added so a future
  strategy needing more context doesn't require another signature change; the three
  Phase 2 strategies accept and ignore it, consistent with how they already ignore
  `requirements`.
* **Fallback and experimentation are orthogonal, not alternative strategies**: fallback
  (which model to retry with on failure) operates at the invocation layer
  (`InvocationOrchestrator`) regardless of which `RoutingStrategy` chose the primary,
  including `ExperimentStrategy` — an experiment-selected primary can still fail over to
  an approved fallback like any other.
* **`FallbackPolicy.maximum_attempts` serves both "maximum invocation attempts" and
  "retry budget"** from the original Phase 4 scope — see ADR-014 for why one field
  covers both, given `RetryPolicy` (Phase 3) already bounds retries within one model.
* **`InMemoryIdempotencyStore` and `InMemoryRoutingDecisionRepository` are single-process
  reference implementations** (thread-safe within one process, via one lock held for the
  full check-then-act sequence) — not safe for multi-instance production deployment.
  DynamoDB-backed implementations of the same protocols (conditional writes for the
  idempotency store) are explicitly Phase 5 scope.
* **Idempotency concurrency dedup is unconditional; response replay is policy-gated**
  (ADR-013) — a concurrent duplicate is always blocked from double-invoking regardless
  of policy, but only a policy with `allow_response_caching=True` retains a completed
  result for a later, non-overlapping duplicate to replay.
* **ADR-010's "Phase 5+" deployed-configuration storage is not implemented in Phase 5**:
  ADR-010 anticipated a DynamoDB/SSM-backed `RoutingPolicyRepository`/`ModelCatalogue`
  adapter for deployed environments, to allow runtime config updates without a redeploy.
  Phase 5 instead bundles `policies/` (YAML) directly into the Lambda deployment package
  (`LocalFileModelCatalogue`/`LocalFileRoutingPolicyRepository`, unchanged from Phase 2) —
  the same two DynamoDB tables Phase 5 *does* provision are for decisions/idempotency
  only (ADR-018), never policy/catalogue configuration. Rationale: policy/catalogue
  changes are infrequent, already version-controlled via git, and reviewed like code;
  introducing a live-updatable config store now would add read-consistency/caching
  complexity (ADR-010's own stated cost) with no demonstrated need at this project's
  scale. This is an explicit scope deferral, not an oversight — revisit if a later phase
  demonstrates a real need for redeploy-free config updates.
* **CDK package renamed `constructs` → `cdk_constructs`**: a local
  `infrastructure/constructs/` package shadowed the real jsii `constructs` package
  (`import constructs._jsii` failed inside `aws_cdk`), so the local package was renamed.
* **`ILocalBundling.try_bundle()`'s actual jsii runtime calling convention is positional**
  (`try_bundle(output_dir, options)`), not the keyword-only signature the generated
  Python type stub declares — confirmed empirically via a real `cdk synth`
  (`infrastructure/bundling.py`, documented inline with `# type: ignore[arg-type]`).
* **CDK template-assertion tests are opt-in, not part of the default `pytest` run**
  (`tests/infra/`, `pytest.mark.infra`, excluded via `pyproject.toml`'s
  `addopts = ... -m "not infra"`): a real `cdk synth` — even via the Docker-free local
  bundling path — costs tens of seconds (the `aws_cdk`/jsii import alone is ~10s, plus a
  `pip install` of the Lambda runtime dependencies), versus low single digits of seconds
  for the rest of the suite combined. Both `dev` and `prod` stacks synthesize once, in one
  `cdk.App`/`app.synth()` call, shared across all 24 assertions (CDK's asset-staging cache
  then bundles the — identical, since Lambda source doesn't vary per environment — Lambda
  code asset only once). Run explicitly with `pytest -m infra` or `make test-infra`.
* **Test count after Phase 5**: 272 tests in the default `pytest` run (up from 217 after
  Phase 4 — 55 new: domain/adapter additions, DynamoDB adapters via moto, and the full
  Lambda handler layer), plus 24 opt-in CDK assertion tests (`pytest -m infra`) not
  counted in that default total.
