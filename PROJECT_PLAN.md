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
- [ ] All domain models from `docs/architecture/domain-glossary.md` implemented and typed
- [ ] All routing strategies listed above implemented and unit-tested
- [ ] CLI route evaluator runs with zero AWS credentials/network access
- [ ] Every reason code in the glossary is producible and asserted in a test
- [ ] `make ci` passes
- [ ] Committed and pushed

### Phase 3 — Bedrock provider adapter
`BedrockModelProvider` behind `ModelProvider`, Converse API request/response mapping,
configurable model IDs/inference profiles, token-usage extraction, stop-reason mapping,
provider error taxonomy, timeout handling, bounded retries with backoff+jitter,
throttling/transient/permanent error classification, safe error messages, logical
alias resolution. Tests via fakes and `botocore.stub.Stubber` only — no live Bedrock
calls in CI. Opt-in manual smoke-test script (env-flag gated, cost-warned, excluded from
CI, no prompt-content logging).

**DoD:**
- [ ] `BedrockModelProvider` implements `ModelProvider` fully via Converse API
- [ ] All listed failure modes covered by tests using fakes/Stubber
- [ ] No client path can reach an arbitrary model ID
- [ ] Manual smoke-test script exists, is opt-in, and is excluded from CI
- [ ] `make ci` passes with no live AWS calls
- [ ] Committed and pushed

### Phase 4 — Fallback, experimentation, and idempotency
Explicit fallback policies + eligibility rules, max attempts/retry budget, deterministic
weighted experiment routing with stable cohort hashing, routing-decision persistence
interface, idempotency interface, concurrent duplicate-request strategy, invocation-
attempt records, final decision aggregation. New ADRs: fallback eligibility, deterministic
experimentation, idempotency strategy, retry/cost amplification controls.

**DoD:**
- [ ] Fallback never triggers for the excluded failure categories (validation, authz,
      policy denial, cost rejection, unsupported capability, malformed config)
- [ ] Retry/fallback attempts are bounded and tested at the boundary
- [ ] Experiment cohort assignment is deterministic and boundary-tested
- [ ] Idempotency covers repeated and concurrent duplicate requests, with expiry
- [ ] 4 new ADRs added
- [ ] `make ci` passes
- [ ] Committed and pushed

### Phase 5 — AWS CDK infrastructure and serverless API
CDK v2 Python stacks: API Gateway REST API, inference Lambda, health/ready endpoints,
DynamoDB (config + decisions/idempotency), CloudWatch Log Groups, least-privilege IAM,
Lambda aliases, outputs, tags. One authorization model chosen (IAM or JWT) and recorded
as an ADR. On-demand billing, TTL, encryption, PITR by environment, log retention,
throttling, request-size controls, reserved concurrency, environment-specific removal
policies, teardown support. CDK template/IAM/encryption/retention/public-access/
removal-policy/endpoint-authz assertion tests. No VPC for Lambda without a concrete
justification; no NAT Gateway.

**DoD:**
- [ ] All 6 endpoints deployed and reachable in a dev environment
- [ ] Authorization ADR recorded and enforced
- [ ] CDK tests cover IAM, encryption, retention, removal policy, public access
- [ ] `cdk destroy` fully tears down dev environment with no orphaned resources
- [ ] Committed and pushed

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
| Phase 1 — Foundation and architecture | Complete | `b059a41` (+ `ee55487` username fix) |

## Remaining milestones

| Phase | Title |
|---|---|
| 2 | Domain model and local routing engine |
| 3 | Bedrock provider adapter |
| 4 | Fallback, experimentation, and idempotency |
| 5 | AWS CDK infrastructure and serverless API |
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
