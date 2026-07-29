# CI/CD guide

How `.github/workflows/pr.yml` and `deploy.yml` work, the one-time manual setup they
depend on, branch-protection recommendations, and rollback guidance. See
[ADR-025](../adr/0025-github-oidc-deploy-role-design.md),
[ADR-026](../adr/0026-pr-and-deploy-workflow-separation.md), and
[ADR-027](../adr/0027-iac-security-scanning-approach.md) for the design rationale
behind what follows.

## Overview

* **`pr.yml`** — every pull request (including from forks): lint/format/typecheck,
  unit+contract tests with coverage, CDK assertion tests, an IaC security scan
  (cdk-nag + cfn-lint), a dependency vulnerability scan (pip-audit), and a secret scan
  (gitleaks). No AWS credentials anywhere in this file — nothing to withhold from a
  fork PR, by construction (ADR-026).
* **`deploy.yml`** — triggered by a push to `main` (i.e. after a PR merges) or manually
  via "Run workflow". Deploys `ModelRouter-dev` automatically, then `ModelRouter-prod`
  only after a human approves the `prod` Environment's protection rule.
* **`pricing-freshness-reminder.yml`** — optional, monthly: opens a tracking issue to
  review `policies/model_catalogue.yaml`'s pricing against current AWS Bedrock pricing
  (`docs/cost/cost-estimation-guide.md`).

## One-time manual setup

Nothing in `deploy.yml` can run until these steps are done once, by a human with real
AWS credentials (`aws configure` / SSO) and repository admin access. This is a
deliberate chicken-and-egg root of trust (ADR-025) — none of it is automatable from
inside the pipeline it enables.

### 1. Bootstrap CDK and deploy the OIDC stack

```bash
cdk bootstrap aws://ACCOUNT_ID/REGION   # once per account/Region — see deployment-and-teardown.md
cd infrastructure
cdk deploy GitHubOidc
```

This creates the OIDC provider and the two deploy roles
(`github-actions-deploy-dev`, `github-actions-deploy-prod`) that `deploy.yml` assumes.

If your repository isn't `lapczyna/aws-model-router`, override the org/repo before
deploying: `GITHUB_OIDC_ORG=<org> GITHUB_OIDC_REPO=<repo> cdk deploy GitHubOidc`.

### 2. Create the `dev` and `prod` GitHub Environments

Repository **Settings → Environments → New environment**, once each for `dev` and
`prod`. For each, add these **Environment variables** (Settings → Environments →
`<name>` → Variables — not secrets; an AWS account ID and Region are not sensitive):

| Variable | Value |
|---|---|
| `AWS_ACCOUNT_ID` | your AWS account ID |
| `AWS_REGION` | the Region you deployed to (defaults to `us-east-1` if unset) |

### 3. Add a required-reviewers protection rule to `prod`

Settings → Environments → `prod` → **Deployment protection rules → Required
reviewers** → add yourself (or your team). This is what pauses `deploy-prod` in
`deploy.yml` for manual approval — `environment: prod` in the job definition is what
makes the rule apply; there is no equivalent gate on `dev` (deliberately — see
ADR-026).

### 4. Branch protection on `main`

Settings → Branches → add a rule for `main`:

* Require a pull request before merging (require at least one approval).
* Require status checks to pass before merging — select `pr.yml`'s six job names
  (`Lint, format, typecheck`, `Unit + contract tests (coverage)`,
  `CDK assertion tests`, `IaC security scan (cdk-nag + cfn-lint)`,
  `Dependency vulnerability scan (pip-audit)`, `Secret scan (gitleaks)`).
* Require branches to be up to date before merging.
* Do not allow direct pushes to `main` (no bypass for admins, if you want the rule to
  actually hold).

This is what makes ADR-026's separation meaningful in practice: without it, someone
could push directly to `main` without ever running `pr.yml`, triggering `deploy.yml`
with unreviewed code.

## Before pushing: run the same checks locally

```bash
make ci              # ruff, black --check, mypy, pytest
make test-infra       # pytest -m infra
CDK_NAG_ENABLED=true cdk synth -c env=dev   # from infrastructure/ — the IaC security scan
```

## Rollback

There is no automated rollback action in `deploy.yml` — CDK/CloudFormation's own
mechanics already cover the two failure modes that matter:

* **A deployment fails partway**: CloudFormation automatically rolls the stack back to
  its last stable state — no action needed.
* **A deployment succeeds but the new code is wrong**: re-run `deploy.yml` via
  **Actions → Deploy → Run workflow**, selecting the last-known-good commit or tag from
  the branch/ref picker. This redeploys exactly that historical state through the same
  reviewed pipeline, rather than requiring a separate rollback mechanism to trust.

See [`disaster-recovery.md`](disaster-recovery.md) for scenarios beyond a bad
deployment (full stack loss, a Bedrock Region incident, DynamoDB data loss).

## Why some PR checks use targeted, documented suppressions

`pr.yml`'s `iac-security-scan` and `dependency-scan` jobs each ignore a small, specific
set of findings — never a blanket bypass. See
[ADR-027](../adr/0027-iac-security-scanning-approach.md) for the cdk-nag/cfn-lint
suppressions (each tied to an ADR or a documented AWS resource-schema gap) and the
`dependency-scan` job's inline comments for the pinned dev-tooling CVE IDs (tracked for
removal the next time Dependabot proposes a version bump for that package).
