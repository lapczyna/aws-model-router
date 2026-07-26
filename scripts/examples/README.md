# Example requests for `scripts/evaluate_route.py`

Each file is a JSON `InferenceRequest` (snake_case — see the note in
`scripts/evaluate_route.py`) demonstrating a distinct routing outcome against the
sample configuration in `policies/`:

| File | Demonstrates |
|---|---|
| `default_policy_fallback.json` | Application with no dedicated policy file falls back to `policies/default_policy.yaml`; preferred-model strategy selects `economical-text-primary`. |
| `support_assistant_balanced.json` | `support-assistant`'s lowest-cost strategy selects the eligible `balanced-text-primary` candidate. |
| `cost_limit_exceeded.json` | A client-supplied cost ceiling tighter than the policy's own limit excludes the only eligible candidate → `NO_ELIGIBLE_MODEL`. |
| `capability_not_permitted.json` | `support-assistant`'s policy doesn't allow `advanced-reasoning` → `REQUIRED_CAPABILITY_UNAVAILABLE`. |

Run any of them from the repository root:

```bash
python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
```
