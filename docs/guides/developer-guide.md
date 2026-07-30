# Developer guide

Onboarding for a new contributor: repository layout, local setup, and where new code
belongs. See [`../architecture/overview.md`](../architecture/overview.md) for the
architectural narrative this layout implements, and
[`../architecture/domain-glossary.md`](../architecture/domain-glossary.md) for the domain
vocabulary (`RoutingPolicy`, `RoutingDecision`, `InferenceRequest`, etc.) used throughout.

## Repository layout

```
src/
  domain/          Pure business logic — no AWS SDK imports, no I/O. Pydantic models,
                   routing strategies, cost/fallback/experiment rules.
  application/     Use-case orchestration (RouteEvaluationService,
                   InvocationOrchestrator) — coordinates domain + ports, still no
                   concrete AWS calls.
  adapters/        Concrete implementations of `domain.ports` protocols: Bedrock,
                   DynamoDB, local-file config, in-memory fakes, EMF metrics.
  handlers/        The Lambda entry point (`api_handler.py`) and request/response
                   mapping between HTTP JSON and internal domain models.
  shared/          Cross-cutting utilities with no business logic: clock, identifier
                   generation, structured logging.
infrastructure/    AWS CDK app (Python) — one stack per environment, plus a
                   bootstrap-only GitHubOidc stack.
tests/
  unit/            Fast, no-AWS-credential tests mirroring the src/ layout.
  contract/        Schema/contract-level tests (e.g. policy schema examples).
  infra/           CDK assertion tests (`Template.from_stack(...)`) — no real AWS calls
                   either, but requires the `infra` extra and a system Node.js install
                   (jsii).
  support/         Shared test fakes/fixtures (`fakes.py`) — not a source of truth for
                   how a script should build these objects; see the note in
                   `scripts/run_demo_scenarios.py` about why scripts don't import from
                   `tests/`.
policies/          Version-controlled model catalogue and routing policy YAML/JSON.
scripts/           Local, credential-free (mostly) developer scripts — see
                   `scripts/README.md`.
docs/              Everything else: architecture, security, cost, operations, guides.
```

`domain` → `application` → `adapters`/`handlers` is a one-way dependency direction
(ADR-002): `domain` never imports from `adapters`, so any provider (Bedrock today) or
storage backend (DynamoDB today) can be swapped without touching business logic.

## Local setup

```bash
pip install -e ".[dev]"          # domain/application/adapters/handlers + test tooling
pip install -e ".[dev,infra]"    # also CDK, for infrastructure/ + tests/infra
```

The `infra` extra additionally requires a system Node.js install (CDK's Python bindings
are jsii-bridged to the Node.js CDK toolkit even for pure-Python API calls like
`Template.from_stack(...)`).

## Running checks

```bash
python -m pytest tests/ -q                    # unit + contract tests (no AWS, no Node)
python -m pytest -m infra -q                  # CDK assertion tests (needs the infra extra)
python -m mypy src/                           # strict mode (pyproject.toml)
python -m ruff check .
python -m black --check .
```

All four are required in CI (`.github/workflows/pr.yml`) and should pass locally before
opening a PR. `pyproject.toml`'s `[tool.mypy]` sets `strict = true`; a new module without
type annotations will fail immediately, by design.

## Where new code belongs

* **New provider** (e.g. a second LLM vendor): implement `domain.ports.ModelProvider` as
  a new `adapters/<provider>/` package — no `domain`/`application` change required
  (ADR-002, NFR-6.1).
* **New routing strategy**: add a class implementing `domain.strategy.RoutingStrategy`,
  register it in `domain.strategy.get_strategy`, add a `RoutingStrategyType` enum value.
  See `tests/unit/domain/test_strategy.py` for the existing pattern.
* **New storage backend** for decisions/idempotency/health: implement the matching
  `domain.ports` protocol (`RoutingDecisionRepository`, `IdempotencyStore`,
  `ModelHealthRepository`) — see ADR-018/ADR-020 for the design reasoning behind the
  existing DynamoDB/in-memory implementations.
* **New HTTP route**: `src/handlers/api_handler.py`'s `dispatch()` function, plus
  request/response mapping in `handlers/request_mapping.py` — see ADR-016 for why this
  project uses a single shared Lambda handler rather than one function per route.

## Conventions

* Conventional Commits for commit messages (`feat:`, `fix:`, `docs:`, etc.).
* No comments explaining *what* code does (names should do that) — only *why*, for a
  non-obvious constraint, invariant, or workaround.
* Every ADR in `docs/adr/` records a real, hard-to-reverse decision with context and
  alternatives considered — see `docs/adr/README.md` for when to add one.
