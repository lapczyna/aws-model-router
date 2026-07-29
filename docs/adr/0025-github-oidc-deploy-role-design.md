# ADR-025: GitHub OIDC deploy role design

## Status
Accepted

## Context
Phase 8 requires GitHub Actions to deploy to AWS via OIDC — no long-lived AWS access
keys stored as GitHub secrets (`docs/requirements.md` NFR-2.3's API-key rejection
extends naturally to deploy credentials too). The open design question: what IAM
permissions should the GitHub-trusted role itself carry? A naive approach grants the
OIDC role broad permissions directly (often `AdministratorAccess`, since `cdk deploy`
can create almost any resource type depending on what the app defines) — which would
undo this project's Phase 7 least-privilege discipline (ADR-022) at exactly the point
where a compromised workflow or leaked token would matter most.

## Decision
`infrastructure/stacks/github_oidc_stack.py`'s `GitHubOidcStack` creates one
`iam.OpenIdConnectProvider` for `token.actions.githubusercontent.com`, and two IAM
roles (`github-actions-deploy-dev`, `github-actions-deploy-prod`) — each trusted only
via a `StringLike` condition on `token.actions.githubusercontent.com:sub` scoped to
that specific GitHub **Environment** (`repo:{org}/{repo}:environment:dev` /
`:environment:prod`), not merely the repository or branch. This means a workflow job
must both come from this exact repository *and* explicitly target the matching GitHub
Environment (`environment: dev` / `environment: prod` in the job definition,
`deploy.yml`) to assume the corresponding role — a job that omits `environment:` cannot
assume either role at all.

**Each deploy role's own IAM policy grants exactly one action:
`sts:AssumeRole`, on exactly the three roles `cdk bootstrap` itself already created**
(`cdk-hnb659fds-deploy-role-*`, `cdk-hnb659fds-file-publishing-role-*`,
`cdk-hnb659fds-lookup-role-*`) — never a broader permission directly. This is CDK's own
documented deployment model: `cdk deploy` assumes the bootstrap `deploy-role` to push
CloudFormation change sets and the `file-publishing-role` to upload assets to the
bootstrap S3 bucket; CloudFormation itself then assumes a *separate* bootstrap
`cfn-exec-role` (not touched by this stack at all) to actually create/update resources.
The broad, resource-creating permissions already live on that `cfn-exec-role` — a
concern `cdk bootstrap` establishes and that operators can customize independently via
`cdk bootstrap --cloudformation-execution-policies` — not something this stack
re-implements or needs to know about.

## Consequences
* The GitHub-trusted role's own policy is tiny, auditable at a glance, and does not
  grow as `ModelRouterStack` adds new resource types — a new AWS service integration
  never requires touching `GitHubOidcStack`.
* This stack must be deployed **manually, once, by a human with real AWS credentials**
  before `deploy.yml` can function at all — the chicken-and-egg root of trust
  (`cdk deploy GitHubOidc`, documented in `docs/operations/ci-cd.md`). It is never
  deployed by the pipeline it enables.
* Compromise of the `dev` deploy role's OIDC trust does not grant any path to the
  `prod` role — the `sub` claim condition is per-environment, and each role's
  `AssumeRole` grant is scoped to the same account's bootstrap roles either way
  (single-account deployment model, ADR-005) but the two GitHub Environments remain
  independently governable (e.g. `prod` can require reviewers where `dev` doesn't —
  ADR-026).
* If `cdk bootstrap` is ever re-run with a non-default qualifier (not `hnb659fds`), the
  hardcoded bootstrap role ARNs in `github_oidc_stack.py` must be updated to match —
  documented as a follow-up if this project's bootstrap qualifier ever changes, not
  parameterized speculatively today.

## Alternatives considered
* **Broad permissions (e.g. `AdministratorAccess` or a hand-picked wildcard policy)
  directly on the GitHub-trusted role** — rejected: exactly the over-privileged pattern
  ADR-022 spent Phase 7 removing from the Lambda execution role; a leaked OIDC trust
  condition or compromised workflow would otherwise grant broad account access
  directly, rather than being bounded by whatever `cdk bootstrap`'s own
  (separately governable) execution policy allows.
* **One shared deploy role for both dev and prod`, gated only by which stack name is
  passed to `cdk deploy`** — rejected: relies entirely on workflow-file discipline
  (trusting that no job accidentally passes `ModelRouter-prod` to a dev-triggered run)
  rather than an IAM-enforced boundary; per-environment roles make the trust boundary a
  property of AWS IAM, not of the workflow author's care.
* **Repository- or branch-scoped `sub` claims** (`repo:{org}/{repo}:ref:refs/heads/main`)
  instead of Environment-scoped — rejected: GitHub Environment-scoped claims are the
  mechanism that also unlocks Environment protection rules (required reviewers,
  ADR-026) in the same job step; branch-scoped claims would authenticate the same job
  without gaining that additional, independently-configurable approval gate.
