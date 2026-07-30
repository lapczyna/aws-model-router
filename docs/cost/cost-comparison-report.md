# Cost comparison report

What `scripts/cost_comparison_report.py` computes, why it matters for the router's value
proposition, and how to reproduce it. See
[`cost-estimation-guide.md`](cost-estimation-guide.md) for how estimation itself works
and why it diverges from real AWS billing — this report is about *relative* cost across
models for the same workload, not absolute billing accuracy.

## What this measures

For each model in `policies/model_catalogue.yaml`, and for three representative
workloads (a short chat turn, a medium document summary, a long document analysis), the
script computes `DefaultCostEstimator`'s estimated cost per request, then projects a
monthly cost at a configurable request volume. This is the same deterministic estimation
logic the router uses at request time — no AWS credentials, no Bedrock call.

```bash
python scripts/cost_comparison_report.py
python scripts/cost_comparison_report.py --requests-per-day 50000
```

## Results (current catalogue, illustrative sample pricing)

At 10,000 requests/day, sustained for 30 days:

| Workload | Model | Est. cost/request | Multiple of cheapest | Est. monthly cost |
|---|---|---|---|---|
| short-chat-turn (~200 input chars, 200 max output tokens) | economical-text-primary | $0.000262 | 1.0x | ~$79 |
| | balanced-text-primary | $0.003150 | 12.0x | ~$945 |
| | balanced-text-secondary | $0.005200 | 19.8x | ~$1,560 |
| | advanced-reasoning-primary | $0.015750 | 60.1x | ~$4,725 |
| document-summary (~4,000 input chars, 500 max output tokens) | economical-text-primary | $0.000875 | 1.0x | ~$263 |
| | balanced-text-primary | $0.010500 | 12.0x | ~$3,150 |
| | balanced-text-secondary | $0.020000 | 22.9x | ~$6,000 |
| | advanced-reasoning-primary | $0.052500 | 60.0x | ~$15,750 |
| long-document-analysis (~40,000 input chars, 1,500 max output tokens) | economical-text-primary | $0.004375 | 1.0x | ~$1,313 |
| | balanced-text-primary | $0.052500 | 12.0x | ~$15,750 |
| | balanced-text-secondary | $0.116000 | 26.5x | ~$34,800 |
| | advanced-reasoning-primary | $0.262500 | 60.0x | ~$78,750 |

## What this demonstrates

* **Capability-tier misrouting is the single biggest cost lever this router controls.**
  Sending a workload that only needs `economical-text` to `advanced-reasoning` costs
  roughly 60x more for the identical workload, across all three sample sizes — nothing
  else in this comparison comes close. This is exactly what policy-driven capability
  allowlisting (`RoutingPolicy.allowed_capabilities`) and per-application policy
  configuration are for: an application whose actual need is "summarize a document," not
  "solve a hard reasoning problem," should never be configured with access to the
  premium tier at all.
* **Within a capability tier, model choice still matters, just less dramatically.**
  `balanced-text-secondary` (a deliberately pricier backup — see
  `policies/model_catalogue.yaml`'s comment) costs 1.7x–2.2x more than
  `balanced-text-primary` for the same workload. This is the `lowest_cost` routing
  strategy's job (`support-assistant.yaml`'s configured strategy) — automatically
  preferring the cheaper of two eligible models rather than requiring a human to notice.
  See `test_lowest_cost_strategy_selects_cheapest_and_tags_reason_code`
  (`tests/unit/domain/test_strategy.py`) for where this is proven at the unit level.
* **Cost scales linearly with output-token cap, not just input size.** Because
  `DefaultTokenEstimator` estimates output cost against the *requested maximum*, not the
  actual generated length (see `cost-estimation-guide.md`), a policy's
  `maximum_output_tokens` limit is a direct cost lever independent of prompt size —
  visible in how the ratio between workloads' absolute costs tracks their
  `maximum_output_tokens` values as much as their input size.

## Caveats

* Pricing figures are the sample `policies/model_catalogue.yaml` values — illustrative,
  realistic Bedrock on-demand pricing as of when this catalogue was last updated, not
  necessarily current AWS list pricing. Reproduce this report after updating
  `pricing_version` to get numbers reflecting your actual configured catalogue.
* This report intentionally does not account for retry/fallback multiplication (see
  `cost-estimation-guide.md`'s "Retry/fallback cost multiplication") — it compares
  single-invocation cost across models, not worst-case incident cost.
* Real billed cost still requires AWS Cost Explorer/Budgets — this remains an estimate,
  same as every other cost figure this router produces (ADR-005).
