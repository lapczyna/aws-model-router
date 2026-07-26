# Security Policy

## Status

`aws-model-router` is a public reference implementation and portfolio project. It is not
an officially supported product and carries no service-level agreement. That said, it is
built with production-grade security discipline, and reports of genuine vulnerabilities
are welcome and will be treated seriously.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a suspected security vulnerability.

Instead, report it privately via GitHub's
["Report a vulnerability"](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
flow (Security tab → Advisories → "Report a vulnerability") on this repository, or by
emailing **lapczynski.artur@gmail.com** with a description of the issue, reproduction
steps, and potential impact.

You can expect an initial response within 5 business days. This is a solo-maintained
portfolio project, so response times may vary; critical issues (e.g. anything that could
allow bypassing model allowlists, authorization, or cost controls) will be prioritized.

## Scope

In scope:

* The routing engine and domain logic (`src/domain/`, `src/application/`)
* Provider adapters (`src/adapters/`)
* Lambda handlers (`src/handlers/`)
* AWS CDK infrastructure definitions (`infrastructure/`)
* CI/CD workflows (`.github/workflows/`)

Out of scope:

* Vulnerabilities in upstream dependencies (report these upstream; if a fix requires a
  version bump here, a normal issue is fine)
* Findings that require an attacker to already have privileged AWS account access equal
  to or exceeding the router's own execution role
* Denial-of-service findings that rely purely on the reporter's own AWS account limits

## Security principles this project follows

These are described in full in `docs/adr/` and, from Phase 7 onward, in a dedicated
threat model and security architecture guide under `docs/security/`. In summary:

* Clients never supply raw provider model IDs — only logical capabilities/aliases
  resolved through trusted, server-side configuration (see
  [ADR-006](docs/adr/0006-model-aliases-instead-of-client-supplied-model-ids.md)).
* Least-privilege IAM for every AWS resource; no wildcard Bedrock/DynamoDB permissions.
* No API keys as a primary identity mechanism; IAM or JWT-based authorization only
  (decision recorded in Phase 5).
* No raw prompts or responses are logged or persisted by default (see
  [ADR-008](docs/adr/0008-metadata-only-audit-records-by-default.md)).
* All CI/CD deployment uses GitHub OIDC — no long-lived AWS access keys are stored in
  GitHub secrets (Phase 8).
* Dependencies are pinned and scanned for known vulnerabilities in CI (Phase 8).

## Supported versions

Pre-1.0, only the `main` branch is supported. There are no maintained release branches at
this stage of development.
