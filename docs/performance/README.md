# Performance documentation

* [`routing-benchmark.md`](routing-benchmark.md) — what `scripts/benchmark_routing.py`
  measures (in-process routing-decision latency), what it deliberately doesn't (real
  Bedrock/Lambda/API Gateway latency, which require a real deployment), and how to
  reproduce it (Phase 9).

See [`docs/security/resilience-test-plan.md`](../security/resilience-test-plan.md) for
the correctness-under-concurrency/fault-injection side of Phase 9 — this directory is
about speed, that one is about correctness under load.
