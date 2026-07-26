# Contributing to aws-model-router

This project is developed as a portfolio-quality reference implementation, but it follows
the same engineering discipline expected of a production AWS platform component. This
guide describes how the repository is organized, how changes are proposed, and what is
expected of a contribution.

## Project structure

See [README.md](README.md#repository-structure) for the full repository layout. The
important boundary to preserve when contributing:

| Layer | Path | Rule |
|---|---|---|
| Domain | `src/domain/` | Pure Python. No `boto3`, no AWS SDKs, no framework imports. |
| Application | `src/application/` | Orchestrates domain logic via interfaces (protocols). No direct AWS SDK calls. |
| Adapters | `src/adapters/` | Implements interfaces defined in the domain/application layers against a real provider (e.g. Bedrock, DynamoDB). |
| Handlers | `src/handlers/` | Thin AWS Lambda entry points. Parse the event, call an application service, format the response. No business logic. |
| Infrastructure | `infrastructure/` | AWS CDK (Python) app defining deployable resources. |

If a change adds an `import boto3` (or any AWS SDK import) inside `src/domain/`, that is a
signal the change belongs in `src/adapters/` instead.

## Development workflow

1. Fork or branch from `main`.
2. Install the development environment (see [README.md](README.md#local-development-setup)).
3. Make focused changes. Prefer several small, reviewable commits over one large commit.
4. Add or update tests for any behavior change. Untested business logic will not be merged.
5. Run the full local verification suite before opening a pull request:

   ```bash
   make ci
   ```

   (equivalent to `black --check .`, `ruff check .`, `mypy`, `pytest`)
6. Update relevant documentation (README, ADRs, `PROJECT_PLAN.md`) in the same change set
   as the code it describes. Documentation drift is treated as a defect.
7. Open a pull request using the provided template.

## Commit messages

This repository uses [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add lowest-estimated-cost routing strategy
fix: correct token estimation for structured-output capability
docs: add ADR for fallback eligibility rules
test: add contract tests for Bedrock throttling classification
chore: bump boto3 pin
```

## Coding standards

* **Python 3.12**, fully type-hinted. `mypy --strict` must pass.
* Formatting via **Black**, linting via **Ruff** — both enforced in CI and pre-commit.
* **No naive datetimes.** Use timezone-aware UTC timestamps everywhere (`ruff` rule `DTZ`
  enforces this).
* **Use `Decimal` for money.** Never use `float` for cost or pricing calculations.
* **Immutable domain objects** where practical (`pydantic` models with `frozen=True`, or
  `@dataclass(frozen=True)`).
* **Dependency inversion**: application services depend on protocols
  (`src/domain`/`src/application` interfaces), not on concrete adapters.
* **No hardcoded model pricing or model IDs** in business logic — these are configuration.
* **No logging of raw prompts, responses, or credentials.** See
  [SECURITY.md](SECURITY.md) and `docs/architecture/overview.md` for the sanitized
  logging contract.

## Testing expectations

| Test type | Location | Requires AWS credentials? |
|---|---|---|
| Unit | `tests/unit/` | No |
| Contract | `tests/contract/` | No (uses fakes / `botocore.stub.Stubber`) |
| Integration | `tests/integration/` | No, unless explicitly marked and opt-in (see Phase 3 smoke tests) |

Automated tests must never require live AWS credentials or make real Bedrock invocations.
Any real-invocation smoke test must be explicitly opt-in, excluded from CI, and clearly
labeled with a cost warning (see Phase 3).

## Architecture Decision Records (ADRs)

Significant, hard-to-reverse decisions are recorded under `docs/adr/`. If your change
introduces a new architectural direction, alters a previous decision, or closes a decision
that was previously open, add or update an ADR. See `docs/adr/README.md` for the template.

## Phased development

This repository is being built incrementally across defined phases described in
[PROJECT_PLAN.md](PROJECT_PLAN.md). Contributions should stay within the scope of the
phase currently in progress; avoid introducing later-phase functionality (e.g., real
infrastructure code before Phase 5) as part of an earlier-phase change.

## Code of conduct

Be respectful and constructive in issues, discussions, and reviews. Assume good faith.
Disagreements about design should be resolved by evidence (tests, benchmarks, ADRs), not
by seniority or volume.
