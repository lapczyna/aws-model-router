# ADR-026: PR and deployment workflow separation

## Status
Accepted

## Context
Phase 8 requires that fork PRs be verified to lack deployment permissions — a common
CI/CD footgun is a single workflow that both validates a PR and has AWS credentials in
scope, where a malicious fork PR can modify workflow YAML in the same PR that runs it
(or exploit `pull_request_target` misuse) to exfiltrate secrets or trigger an
unauthorized deployment. GitHub's own security model already provides strong
primitives here (secrets and elevated permissions are withheld from fork-triggered
`pull_request` workflows by default), but the primitives only help if the workflow
design doesn't fight them.

## Decision
Two entirely separate workflow files, triggered by disjoint events:

* **`pr.yml`** — trigger: `pull_request` (`branches: [main]`) **and** `push`
  (`branches: [main]`, added later — see Consequences). Top-level
  `permissions: contents: read`. No job requests `id-token: write`. No step references
  any AWS credential, role ARN, or secret beyond the default `GITHUB_TOKEN` (used only
  by `gitleaks-action` for its own API calls, not AWS). Every check (lint, typecheck,
  tests, CDK assertion tests, cdk-nag/cfn-lint IaC scan, dependency scan, secret scan —
  ADR-027) runs identically regardless of whether the PR is from a branch on this
  repository or a fork, because nothing in the workflow *can* behave differently — there
  is no credential to withhold or leak in the first place.
* **`deploy.yml`** — trigger: `push` to `main`, and `workflow_dispatch`. **Never**
  `pull_request` or `pull_request_target`. Only a push that has already landed on `main`
  (i.e. already passed PR review and `pr.yml`'s checks, per branch protection —
  `docs/operations/ci-cd.md`) can reach this workflow at all. Each job explicitly
  requests `id-token: write` and targets a named GitHub Environment (`environment: dev`
  / `environment: prod`), which is what makes the OIDC role assumption
  (`aws-actions/configure-aws-credentials`) possible per ADR-025's `sub` claim
  condition.

**Fork PRs are excluded from deployment permissions by construction, not by
configuration a maintainer could forget**: a fork PR can only ever trigger `pr.yml`
(via `pull_request`), and `pr.yml` has no AWS credential path to withhold in the first
place — there is nothing to accidentally leave enabled.

`deploy-prod` additionally requires the `prod` GitHub Environment's required-reviewers
protection rule (configured once in repository settings —
`docs/operations/ci-cd.md`) — a human must approve the job in the Actions UI before it
runs, even though it was already auto-triggered by the push. `deploy-dev` has no such
gate: `dev` is `RemovalPolicy.DESTROY`, cheap to redeploy, and losing fast feedback on
every `main` push would undermine the point of continuous deployment to it.

## Consequences
* Branch protection on `main` (required status checks referencing `pr.yml`'s job
  names, no direct pushes — `docs/operations/ci-cd.md`) is what actually prevents an
  unreviewed change from ever reaching `deploy.yml` — this ADR's separation is
  necessary but not sufficient without that repository setting also being enabled.
* **`pr.yml` gained a `push: branches: [main]` trigger alongside `pull_request`**, added
  once this project's actual practice (direct pushes to `main`, not PR-gated merges —
  `PROJECT_PLAN.md`) made it clear no branch-protection gate was actually enforcing the
  "PR checks pass before `main` changes" property the previous bullet describes. This is
  strictly an *addition*, not a replacement: it gives after-the-fact validation of every
  direct push (and a CI status badge something honest to reflect) without requiring the
  PR-gated flow this project has explicitly chosen not to adopt yet. It does not touch
  this ADR's actual security property — a fork can never push to this repository's `main`
  regardless, so the set of things a fork can trigger is unchanged. Real, pre-merge
  gating of `main` still requires the branch-protection setup this ADR always described;
  this addition only makes the *absence* of that gate less silent.
* A maintainer merging a PR is the only path to a `dev` deployment; a maintainer
  approving the `prod` Environment gate is the only path to a `prod` deployment. Neither
  requires (or grants) the other workflow file's capabilities.
* Adding a new automated check to PR validation never risks touching deployment
  credentials, since `pr.yml` structurally has none — a future contributor extending
  `pr.yml` cannot accidentally introduce a deployment side effect there.

## Alternatives considered
* **One workflow, conditional steps gated by `github.event_name`** — rejected: makes
  the "forks can't deploy" property something a reviewer has to verify by reading
  conditional logic correctly, rather than something structurally true because the
  credential-requesting steps live in a file forks can never trigger.
* **`pull_request_target` for deployment previews** — rejected outright: this event
  runs with the base repository's full permissions and secrets even for fork PRs,
  which is the exact anti-pattern this ADR exists to avoid; not used anywhere in this
  project.
* **Manual approval gate on `dev` too** — rejected: `dev`'s whole purpose is fast
  iteration feedback (ADR-018's `RemovalPolicy.DESTROY` reflects the same "cheap to
  redeploy, low stakes" philosophy); gating it manually would just slow down the
  feedback loop without a corresponding risk reduction `prod`'s gate doesn't already
  cover for anything that actually matters.
