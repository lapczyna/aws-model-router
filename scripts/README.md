# Scripts

Developer and operational scripts.

* [`evaluate_route.py`](evaluate_route.py) — evaluates a routing decision locally,
  without invoking any model or requiring AWS credentials. See
  [`examples/`](examples/) for sample requests and what each demonstrates.

  ```bash
  python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
  ```

* [`bedrock_live_smoke_test.py`](bedrock_live_smoke_test.py) — **makes a real, billable
  Amazon Bedrock call.** Opt-in only: requires
  `AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST=true` in the environment, `--confirm-cost` on
  the command line, and real AWS credentials. Never run by the automated test suite or
  CI. See the script's own docstring for the full usage and safety details.

  ```bash
  export AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST=true
  python scripts/bedrock_live_smoke_test.py --model-alias economical-text-primary --confirm-cost
  ```

* [`openai_live_smoke_test.py`](openai_live_smoke_test.py) — **makes a real, billable
  OpenAI call** (ADR-029). Same opt-in gating as `bedrock_live_smoke_test.py`, plus a
  real OpenAI API key (`OPENAI_API_KEY` environment variable or `--api-key`). Never run
  by the automated test suite or CI.

  ```bash
  export AWS_MODEL_ROUTER_ENABLE_LIVE_SMOKE_TEST=true
  export OPENAI_API_KEY=sk-...
  python scripts/openai_live_smoke_test.py --model-alias balanced-text-openai --confirm-cost
  ```

* [`invoke_lambda_locally.py`](invoke_lambda_locally.py) — invokes the real Lambda
  handler code (`src/handlers/api_handler.py`) against a synthetic API Gateway proxy
  event, without deploying anything. Defaults to fake mode: no AWS credentials required,
  using an in-process `EchoModelProvider` (never a real model) plus in-memory
  idempotency/decision stores, so it exercises the actual request parsing, routing,
  error mapping, and response serialization end to end. `--use-real-services` instead
  calls `build_services()` against a deployed stack (requires AWS credentials and the
  `DECISIONS_TABLE_NAME`/`IDEMPOTENCY_TABLE_NAME` environment variables — see
  [`docs/operations/deployment-and-teardown.md`](../docs/operations/deployment-and-teardown.md));
  `POST /v1/inference` in that mode additionally requires `--confirm-cost`, since it
  makes a real, billable Bedrock call. See [`events/`](../events/) for sample HTTP-shape
  (camelCase) request bodies.

  ```bash
  python scripts/invoke_lambda_locally.py --method GET --resource /v1/models
  python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
      --body events/support_assistant_balanced.json
  ```

* [`benchmark_routing.py`](benchmark_routing.py) — times `RouteEvaluationService.evaluate()`
  in a tight in-process loop (no AWS credentials, no model invocation). See
  [`docs/performance/routing-benchmark.md`](../docs/performance/routing-benchmark.md) for
  what this measures, what it deliberately doesn't, and measured results.

  ```bash
  python scripts/benchmark_routing.py --iterations 3000
  ```

* [`cost_comparison_report.py`](cost_comparison_report.py) — compares estimated cost
  across every catalogued model for representative workloads (no AWS credentials, no
  model invocation). See
  [`docs/cost/cost-comparison-report.md`](../docs/cost/cost-comparison-report.md) for the
  full report and what it demonstrates.

  ```bash
  python scripts/cost_comparison_report.py
  ```

* [`run_demo_scenarios.py`](run_demo_scenarios.py) — narrated walkthroughs of scenarios
  that need scripted behavior rather than a static example file: model-invocation
  fallback, idempotent duplicate requests, model health degradation, observability
  (structured logs + EMF metrics for one request), and cross-provider fallback (Bedrock
  primary, OpenAI fallback, via a real `CompositeModelProvider` — Phase 10a, ADR-029). No
  AWS credentials required. See [`docs/demonstrations.md`](../docs/demonstrations.md) for
  all sample demonstrations, including the ones with existing dedicated scripts/fixtures.

  ```bash
  python scripts/run_demo_scenarios.py                      # run all scenarios
  python scripts/run_demo_scenarios.py --scenario fallback
  python scripts/run_demo_scenarios.py --scenario multi-provider-fallback
  ```
