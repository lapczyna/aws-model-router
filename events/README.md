# Sample events

HTTP-shape (camelCase, matching [`docs/architecture/api-contracts.md`](../docs/architecture/api-contracts.md))
request bodies for `POST /v1/inference` and `POST /v1/routes/evaluate`, used with
[`scripts/invoke_lambda_locally.py`](../scripts/invoke_lambda_locally.py) to exercise the
real Lambda handler locally without deploying anything:

```bash
python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
    --body events/support_assistant_balanced.json
```

* [`support_assistant_balanced.json`](support_assistant_balanced.json) — a normal,
  eligible request (`balanced-text`, within cost/token limits).
* [`capability_not_permitted.json`](capability_not_permitted.json) — requests a
  capability (`advanced-reasoning`) the `support-assistant` policy doesn't allow;
  demonstrates the `422 REQUIRED_CAPABILITY_UNAVAILABLE` response.

These are HTTP-contract (camelCase) request *bodies* only — `invoke_lambda_locally.py`
wraps them into a full API Gateway proxy event itself. For the internal, snake_case
`InferenceRequest` shape consumed directly by `scripts/evaluate_route.py` (no HTTP layer
involved), see [`scripts/examples/`](../scripts/examples/) instead.
