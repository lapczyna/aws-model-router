# Final architecture review (Phase 9)

A retrospective review of the architecture across all nine completed phases, and the
roadmap for what comes after. See [`overview.md`](overview.md) for the narrative
architecture description this review checks against, and
[`../adr/README.md`](../adr/README.md) for the full decision log (28 ADRs as of this
review).

## What this review checked, and how

Not a re-statement of intent — each claim below was verified against the current
codebase during Phase 9, not assumed from earlier phase reports:

* **Domain-layer purity** (ADR-002): `grep` across `src/domain/` and `src/application/`
  for any `boto3`/`aws_cdk` import returns zero matches. The dependency-inversion
  boundary this project has claimed since Phase 1 still holds in practice, not just in
  intent.
* **No adapter leakage into domain/application**: the same layers import nothing from
  `src/adapters/` — every dependency on a concrete provider or storage backend flows
  through a `domain.ports` protocol, confirmed by the same search returning zero matches.
* **Test suite health**: 320 unit/contract tests pass (`python -m pytest tests/ -q`); a
  further 46 CDK assertion tests pass under `pytest -m infra`. `mypy --strict`, `ruff`,
  and `black --check` are all clean across `src/`, `tests/`, `infrastructure/`, and
  `scripts/`.
* **Documentation link integrity**: every relative Markdown link across `docs/`,
  `README.md`, `PROJECT_PLAN.md`, `scripts/README.md`, and `policies/README.md` resolves
  to a real file — checked programmatically (a link-resolution script, not spot-checking
  by eye), zero broken links found.
* **ADR-to-code consistency**: reviewing the fallback/health interaction while building
  Phase 9's fault-injection tests found one real drift between a shipped ADR's claim and
  actual behavior (ADR-011 said the orchestrator always "returns immediately" when no
  model is selected — no longer true once ADR-028's fix shipped). Corrected in the same
  change set rather than left stale. This is presented as a positive example of the
  project's stated verification discipline catching something real, not as evidence
  everything else in the ADR log is equally suspect — the rest were spot-checked and
  found accurate (e.g. the cost-comparison report initially cited a test function name
  that didn't exist verbatim, caught by grep before shipping and corrected).

## What the architecture actually delivers, in one paragraph

A single Lambda (ADR-016) fronts a policy-driven routing engine (ADR-001) that is
entirely provider-independent in its domain/application layers (ADR-002) and currently
backed by Amazon Bedrock (ADR-003). Every routing decision is deterministic and
explainable via reason codes (ADR-007), governed by per-application policy (capability
allowlists, cost/token limits, quality tiers) resolved from version-controlled
configuration (ADR-010), with bounded, policy-controlled fallback (ADR-011) and
idempotency (ADR-013) guarantees. Observability is structured JSON logs plus EMF metrics
with a fixed, enforced field whitelist that makes leaking raw prompt/response content a
defect, not a policy choice, to prevent (ADR-008, ADR-019). Deployment is fully
serverless and pay-per-request (ADR-005) via CDK (ADR-004), authenticated through IAM
SigV4 (ADR-015) with GitHub-OIDC-based CI/CD carrying no long-lived AWS credentials
(ADR-025) and IaC security scanning catching a real deployment-breaking defect before it
would have reached `prod` (ADR-027).

## Known, documented limitations (not fixed, by deliberate choice)

These are not oversights — each has a written rationale in its ADR/threat-model entry:

* **T2 — `applicationId` spoofing**: IAM proves authentication, not a binding to a
  specific claimed `applicationId`. Detective control shipped (Phase 7); the preventive
  fix (`RoutingPolicy.allowed_caller_principal_arns`) is designed but not built. See
  `docs/security/threat-model.md`.
* **Model health tracking is process-local**, not fleet-wide across concurrent Lambda
  execution environments (ADR-020) — a soft signal-quality gap, not a correctness bug.
* **Cross-Region inference profile adoption** was evaluated, not adopted, for the base
  deployment (ADR-023) — Region-level resilience remains a single-Region deployment's
  responsibility today.
* **No content-safety/prompt-injection defense** — this router answers "which model, and
  why," never "is this content safe" (ADR-024); Bedrock Guardrails integration is
  recommended, not built.
* **No sample policy demonstrates `quality_tier` strategy or `preferred_model` combined
  with a configured `fallback_policy`** together in a single static file (found during
  Phase 9's sample-policy review; see `policies/README.md`) — both are exercised in code
  (`scripts/run_demo_scenarios.py`, `tests/unit/domain/test_strategy.py`), just not as a
  shipped example YAML.
* **CI/CD deploys directly from `main`** (no separate PR-gated release branch) once a
  pull request merges — through Phase 8 this ran without branch protection enabled at
  all (an explicit choice, not a placeholder); see
  [ADR-026](../adr/0026-pr-and-deploy-workflow-separation.md) for why the PR/deploy
  workflow separation was designed to be safe either way, since a fork PR never had a
  credential path to exploit regardless of whether branch protection gated `main`.
  Branch protection is now enabled ([PR #15](https://github.com/lapczyna/aws-model-router/pull/15)) — a pull request and all six `pr.yml` checks passing are required
  before anything reaches `main`, closing the gap that ADR-026's design never depended
  on but also never closed on its own.

## Multi-perspective self-review

Five perspectives, each asked to find something real rather than restate what other
docs already claim. Findings are reported whether or not they required action —
"nothing found" is itself a checked claim below, not an assumption.

**1. Security reviewer.** Phase 9 added three new scripts
(`scripts/benchmark_routing.py`, `scripts/cost_comparison_report.py`,
`scripts/run_demo_scenarios.py`); none contains `eval`/`exec`/`subprocess`/`os.system`/
`pickle` (checked via `grep`, not assumed), none handles untrusted input beyond a local
file path argument, and none touches AWS credentials. `tests/unit/handlers/
test_abuse_cases.py` still passes unchanged. No new finding this phase — Phases 7/8
already did the structural security work; this was a regression check, not a fresh audit.

**2. Cost-conscious operator.** `docs/cost/cost-comparison-report.md` quantifies the
single biggest cost lever this router controls: sending a workload to the wrong
capability tier costs roughly 60x more for identical input, dwarfing within-tier model
choice (1.7x–2.2x). Every new Phase 9 script is credential-free and makes zero real
Bedrock calls (verified by construction, not just by convention — see each script's own
docstring) — running any of them, including the benchmark and demo scripts, cannot
incur a bill.

**3. New contributor onboarding.** Every command in `docs/guides/developer-guide.md` was
actually run during this phase (`pip install -e ".[dev]"`, `pytest -m infra`, `mypy`,
`ruff`, `black`), not copied from memory. A repo-wide automated check of every relative
Markdown link (`docs/`, `README.md`, `PROJECT_PLAN.md`, and the `scripts`/`policies`
READMEs) found zero broken references — a new contributor following any doc's links
won't hit a dead end.

**4. Reliability/SRE.** This lens produced the phase's most significant finding:
building the load/fault-injection test suite exposed that health-based exclusion of the
preferred model, combined with the default `preferred_model` routing strategy, caused
*total* request failure instead of falling back to a healthy alternate — fixed in
[ADR-028](../adr/0028-fallback-chain-considers-health-excluded-candidates.md). Re-running
this same lens after the fix, specifically asking "does this fix interact badly with any
*other* strategy," found a second, subtler issue: the fix applies uniformly regardless of
strategy, so it can also substitute a health-excluded experiment arm for a fallback model
— the exact behavior `ExperimentStrategy`'s own docstring says it never performs itself.
Assessed as acceptable rather than a bug (the substitution is always auditable via
`fallback_used`/`FALLBACK_SELECTED`, never silent), documented in both ADR-028 and the
strategy's docstring, and pinned with a dedicated characterization test
(`test_fallback_can_replace_a_health_excluded_experiment_arm_but_marks_it_auditable`).

**5. Hiring-manager/portfolio reviewer.** `git status` shows only the files this phase
intentionally touched — no stray debug files, no accidentally-tracked IDE configuration
(`.idea/` is gitignored, confirmed). The README's status banner, ADR table, and roadmap
table are updated to match the actual current phase rather than left describing Phase 8.
No placeholder "TODO" or "coming soon" content was found in any file this review touched.

No high-priority finding from this review was left unresolved: the reliability finding
(the primary substantive one) was fixed and tested; the others were either confirmed
clean or resolved via documentation where the underlying behavior was judged correct on
inspection.

## Future roadmap

**Near-term, concretely scoped** (each already has a sketched design in its own ADR or
threat-model entry — not speculative, just not yet built):

1. `RoutingPolicy.allowed_caller_principal_arns` — the T2 preventive fix.
2. A DynamoDB-backed `ModelHealthRepository` for fleet-wide health visibility, if a real
   incident demonstrates the in-memory signal misses meaningful degradation (ADR-020).
3. Adopting cross-Region inference profiles for actual Region-level resilience
   (ADR-023's evaluation is already done; adoption is the remaining step).
4. Bedrock Guardrails integration at the point ADR-024 recommends.
5. CloudFormation drift detection, replacing the current "documented operational
   discipline" control for T20 (`docs/security/threat-model.md`).

**Phase 10 — Advanced extensions** (optional; explicitly not started unless requested,
per `PROJECT_PLAN.md`): Bedrock Intelligent Prompt Router as an eligible route target,
multi-provider routing, streaming, tool-use/multimodal routing, quality feedback
collection, offline evaluation, contextual bandits, policy simulation, shadow routing,
canary rollout, automatic health scoring, EventBridge decision events, Step Functions
approval flow, multi-account/tenant isolation, OpenTelemetry, LLM eval platform
integration, prompt caching policy, quota-aware routing, carbon-aware routing research,
governance evidence export. Any adaptive/learning-based routing added under this scope
must start in shadow mode and never control production traffic unvalidated — a
constraint carried forward from Phase 1, not new to this review.

## Conclusion

The architecture holds together as a coherent whole: the layering rules established in
Phase 1 are still true in Phase 9's code, not just its documentation; every phase's
additions integrate with, rather than route around, the ones before it (model health
feeds fallback, which feeds observability, which feeds the security detective controls);
and the one real defect this review's own verification process surfaced (ADR-011's
staleness) was caught and fixed by the same discipline the project has applied
throughout, not by a separate final audit finding something everyone had missed.
