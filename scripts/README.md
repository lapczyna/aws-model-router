# Scripts

Developer and operational scripts.

* [`evaluate_route.py`](evaluate_route.py) — evaluates a routing decision locally,
  without invoking any model or requiring AWS credentials. See
  [`examples/`](examples/) for sample requests and what each demonstrates.

  ```bash
  python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
  ```

Later phases add: the opt-in Bedrock smoke-test script (Phase 3), deployment helpers
(Phase 5), and load/fault-injection scripts (Phase 9).
