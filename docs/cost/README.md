# Cost documentation

* [`cost-estimation-guide.md`](cost-estimation-guide.md) — how the router estimates
  cost, why that estimate diverges from actual AWS billing, the pricing-data update
  process, retry/fallback cost multiplication, and application inference profiles for
  cost attribution (Phase 6).

See [ADR-005](../adr/0005-serverless-pay-per-request-architecture.md) and
[ADR-010](../adr/0010-configuration-storage-approach.md) for the cost-related
architectural decisions the estimation approach builds on, and
`docs/requirements.md#nfr-1--cost` for the cost requirements this documentation
addresses.
