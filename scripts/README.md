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

Later phases add: deployment helpers (Phase 5) and load/fault-injection scripts
(Phase 9).
