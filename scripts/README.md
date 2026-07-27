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

Later phases add: load/fault-injection scripts (Phase 9).
