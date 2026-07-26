# Example requests for `scripts/evaluate_route.py`

Each file is a JSON `InferenceRequest` (snake_case — see the note in
`scripts/evaluate_route.py`) demonstrating a distinct routing outcome against the
sample configuration in `policies/`:

| File | Demonstrates |
|---|---|
| `default_policy_fallback.json` | Application with no dedicated policy file falls back to `policies/default_policy.yaml` (a *policy* fallback — not to be confused with the *model-invocation* fallback below); preferred-model strategy selects `economical-text-primary`. |
| `support_assistant_balanced.json` | `support-assistant`'s lowest-cost strategy selects the eligible `balanced-text-primary` candidate. |
| `cost_limit_exceeded.json` | A client-supplied cost ceiling tighter than the policy's own limit excludes the only eligible candidate → `NO_ELIGIBLE_MODEL`. |
| `capability_not_permitted.json` | `support-assistant`'s policy doesn't allow `advanced-reasoning` → `REQUIRED_CAPABILITY_UNAVAILABLE`. |
| `experiment_routing.json` | `experimental-app`'s weighted experiment strategy deterministically assigns this conversation to the `balanced-text-primary` arm (70% weight) — `EXPERIMENT_ROUTE_SELECTED` appears in `reason_codes`, and both arms show up in `considered_candidates`. |

Run any of them from the repository root:

```bash
python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
```

## What this CLI does and doesn't demonstrate

`evaluate_route.py` only evaluates a route — it never invokes a model (no AWS
credentials needed). That means:

* **Weighted experimentation** (ADR-012) is fully demonstrated here, since cohort
  assignment happens at route-evaluation time.
* **Model-invocation fallback** (ADR-011) — `support-assistant`'s `fallback_policy`
  configuring `balanced-text-secondary` as a backup — is *configured* in
  `policies/applications/support-assistant.yaml` but only actually exercised when a
  model invocation fails, which requires `application.invocation_orchestrator
  .InvocationOrchestrator` and a real (or faked) `ModelProvider`. See
  `tests/unit/application/test_invocation_orchestrator.py` for automated,
  fully-worked examples of fallback in action.
* **Idempotency** (ADR-013) is likewise an invocation-layer concern, demonstrated in
  `tests/unit/application/test_invocation_orchestrator.py` and
  `tests/unit/adapters/memory/test_in_memory_idempotency_store.py`, not by this CLI.
