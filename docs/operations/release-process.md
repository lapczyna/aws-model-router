# Release process

How a release is versioned, tagged, and published for `aws-model-router`. This
codifies a process going forward — see "Current state" below for how the project has
tracked progress up to Phase 9, and why this doc introduces something slightly different
starting now.

## Versioning

[Semantic Versioning](https://semver.org/) against the `version` field in
`pyproject.toml` (currently `0.1.0`). Pre-1.0 (see `SECURITY.md`'s "Supported versions" —
only `main` is supported, no maintained release branches), so:

* A **minor** bump (`0.x.0`) marks a meaningful, externally-visible increment — in
  practice, a completed phase from `PROJECT_PLAN.md` (e.g. Phase 9's performance/polish
  work) or an equivalent standalone feature addition.
* A **patch** bump (`0.x.y`) marks a bug fix or small correction that doesn't add new
  capability — e.g. the ADR-028 fallback fix would have warranted one if it had shipped
  as its own release rather than bundled into Phase 9.
* There is no 1.0 criteria decided yet; when the project's scope stabilizes enough to
  commit to a real backward-compatibility contract, that decision belongs in its own ADR,
  not silently implied by a version bump.

## Cutting a release

1. Confirm `main` is green: `make ci` locally (equivalent to `black --check .`,
   `ruff check .`, `mypy`, `pytest`), and CI passing on GitHub
   (`.github/workflows/pr.yml`'s checks, run again on the `push`-to-main trigger in
   `deploy.yml` — see `docs/operations/ci-cd.md`).
2. Bump `version` in `pyproject.toml` in its own commit
   (`chore: bump version to 0.x.0`).
3. Tag the commit: `git tag -a v0.x.0 -m "v0.x.0 — <one-line summary>"`.
4. Push the tag: `git push origin v0.x.0` (never `--force` a tag that may already be
   public).
5. Generate release notes from Conventional Commits since the previous tag:
   ```bash
   git log <previous-tag>..v0.x.0 --oneline
   ```
   Group by commit type (`feat:`, `fix:`, `docs:`, `chore:`, etc.) into a short summary —
   this project does not maintain a separate `CHANGELOG.md` file; the GitHub Release
   description **is** the changelog, generated from commit history at release time rather
   than hand-maintained continuously (avoids two sources of truth drifting apart).
6. Create the GitHub Release from the pushed tag (`gh release create v0.x.0 --title "..."
   --notes-file <path>`, or the GitHub UI), pointing at the same notes.

None of steps 3–6 happen automatically — this project does not currently run a
tag-triggered release workflow (`deploy.yml` triggers on push-to-main and
`workflow_dispatch`, not on tag push; see
[ADR-026](../adr/0026-pr-and-deploy-workflow-separation.md)). A tag here is a repository
annotation, not a deployment trigger — deploying a specific version to `prod` is the
separate, explicit action described in
[`deployment-and-teardown.md`](deployment-and-teardown.md).

## Current state (as of Phase 9)

Phases 1–8 were tracked via the commit hash marking each phase's completion, recorded in
`PROJECT_PLAN.md`'s "Completed milestones" table — no annotated git tags or GitHub
Releases were created for them. This doc introduces the tag/release process above
starting from whenever it's adopted; retroactively tagging earlier phases is a
repository-affecting action for the user to decide on explicitly, not something applied
automatically by writing this document.

## Rollback

See [`ci-cd.md`](ci-cd.md)'s "Rollback" section — `deploy.yml`'s
**Actions → Deploy → Run workflow** accepts any branch/ref, including a tag, which is
exactly what tagging a release enables: redeploying a specific, known-good historical
state through the same reviewed pipeline, rather than needing a separate rollback
mechanism. `policies/` configuration changes deploy through this same path (ADR-010) — a
bad policy change rolls back the same way as any other code change.

## Rotating the OpenAI API key

Not tied to a release, but documented here alongside the other operational-credential
guidance: the OpenAI API key (`OpenAiApiKeySecret`, provisioned only if
`policies/model_catalogue.yaml` declares an `openai` model — [ADR-029](../adr/0029-multi-provider-routing-openai.md))
has no automatic rotation, since OpenAI exposes no rotate-in-place API for Secrets
Manager's native rotation Lambdas to call (see the `AwsSolutions-SMG4` suppression in
`infrastructure/cdk_constructs/lambda_construct.py` and `threat-model.md`'s T24). To
rotate it manually:

1. Generate a new API key in the OpenAI dashboard.
2. `aws secretsmanager put-secret-value --secret-id <OpenAiApiKeySecret ARN, from the
   `cdk deploy` output> --secret-string <new key>`.
3. The next Lambda cold start picks up the new value (fetched once per cold start, not
   cached indefinitely) — no redeploy needed, but a warm execution environment keeps
   using the old key until it's recycled. For an immediate cutover, force new cold
   starts (e.g. a trivial Lambda configuration update) rather than waiting.
4. Revoke the old key in the OpenAI dashboard once confident the new one is in use.
