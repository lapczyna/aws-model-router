## Summary

<!-- What does this change do, and why? Reference the relevant PROJECT_PLAN.md phase. -->

## Phase / scope

- [ ] This change stays within the scope of the current `PROJECT_PLAN.md` phase
- [ ] No later-phase functionality (e.g. real AWS infrastructure before Phase 5, live
      Bedrock calls before Phase 3) was introduced

## Type of change

- [ ] `feat` — new functionality
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `test` — tests only
- [ ] `refactor` — no behavior change
- [ ] `chore` — tooling, dependencies, CI

## Architecture / boundaries

- [ ] `src/domain/` contains no AWS SDK or framework imports
- [ ] New AWS interactions are implemented behind an adapter, not inline in domain or
      application code
- [ ] Lambda handlers (if touched) remain thin (parse → call application service → format)

## Testing

- [ ] Tests were added or updated for this change
- [ ] `make ci` passes locally (`black --check`, `ruff check`, `mypy`, `pytest`)
- [ ] No test requires live AWS credentials or a real Bedrock invocation

## Security & cost

- [ ] No raw prompts, responses, credentials, or secrets are logged
- [ ] No new hardcoded model IDs, pricing, or credentials were introduced
- [ ] Any new AWS resource follows least-privilege IAM and pay-per-request billing

## Documentation

- [ ] README / `docs/` / ADRs updated if this change affects architecture, API contracts,
      or developer workflow
- [ ] `PROJECT_PLAN.md` milestones updated if this change completes or starts a phase

## Related issues

<!-- Closes #... -->
