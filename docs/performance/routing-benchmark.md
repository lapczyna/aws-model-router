# Routing benchmark and latency report

What this measures, what it deliberately doesn't, and how to reproduce it. See
[`docs/security/resilience-test-plan.md`](../security/resilience-test-plan.md) for the
concurrency/fault-injection side of Phase 9, which is about correctness under load, not
raw speed.

## What's measured

`scripts/benchmark_routing.py` times `RouteEvaluationService.evaluate()` directly, in a
tight loop, entirely in-process:

```bash
python scripts/benchmark_routing.py --iterations 3000
```

This is policy resolution (`LocalFileRoutingPolicyRepository`, in-memory after initial
load), candidate filtering (`domain.filtering.build_route_candidates`), token/cost
estimation, and strategy selection — every piece of routing *logic* this project owns.
There is no network I/O, no disk I/O per call (the YAML config is loaded once, not
re-parsed per request), and no Bedrock call.

## What's deliberately not measured

* **A real Bedrock `InvokeModel`/`Converse` call.** Model inference latency (typically
  hundreds of milliseconds to several seconds, depending on model size and output length)
  is by far the dominant cost of an actual `/v1/inference` request, and it is entirely
  outside this project's control. Benchmarking it here would measure Bedrock, not the
  router, and could misleadingly suggest the router adds meaningful latency to a request
  when in reality routing is a rounding error next to model inference.
* **Real Lambda cold starts, API Gateway overhead, or DynamoDB read/write latency.**
  These require an actual deployed stack (`cdk deploy`), which remains the user's action
  — see [`resilience-test-plan.md`](../security/resilience-test-plan.md) for the same
  boundary applied to load/fault-injection testing.

## Measured results (illustrative, not a guarantee)

Run on the development machine used to build this project (single-threaded, warm
Python process, 100 untimed warmup iterations before measuring 3,000 timed calls against
`scripts/examples/support_assistant_balanced.json`):

| Percentile | Latency |
|---|---|
| min | ~0.02 ms |
| median | ~0.02 ms |
| mean | ~0.02 ms |
| p95 | ~0.03 ms |
| p99 | ~0.04 ms |
| max | ~0.12–0.21 ms (occasional GC/scheduler noise) |
| Throughput (single-threaded) | ~40,000+ decisions/sec |

**These absolute numbers are hardware- and Python-version-dependent — reproduce
`scripts/benchmark_routing.py` on your own machine for numbers you can rely on.** What
*is* portable is the shape: routing decisions are sub-millisecond and dominated by
nothing but in-memory dict/list operations over a small (single-application) candidate
set. In a real deployment, this means the router's own contribution to end-to-end
request latency is negligible next to a Bedrock call — routing overhead is not a
capacity-planning concern for this architecture.

## Reproducing

```bash
pip install -e ".[dev]"
python scripts/benchmark_routing.py --iterations 3000
python scripts/benchmark_routing.py --iterations 3000 --json   # machine-readable
python scripts/benchmark_routing.py --request scripts/examples/experiment_routing.json
```

## Interpreting a regression

If a future change makes this benchmark meaningfully slower (say, 10x), the likely
causes, in order of likelihood given this codebase's structure:

1. A new per-request operation that isn't O(1)/O(small-catalogue-size) — e.g. an
   accidental re-parse of the YAML catalogue/policy files per call instead of once at
   startup (`LocalFileModelCatalogue`/`LocalFileRoutingPolicyRepository` are expected to
   load once and stay in memory).
2. A new synchronous I/O call introduced into `RouteEvaluationService.evaluate()` or
   anything it transitively calls (this method must remain I/O-free by design — the only
   I/O-performing collaborator it accepts is `ModelHealthRepository.get_health()`, and
   the in-memory implementation is itself O(1)).
3. Accidental O(n²) behavior in candidate filtering as the model catalogue grows —
   `test_five_hundred_sequential_requests_complete_in_a_generous_time_bound`
   (`tests/unit/application/test_load_and_fault_injection.py`) is a coarse tripwire for
   this class of regression, but this benchmark is the precise tool to confirm and
   quantify it.
