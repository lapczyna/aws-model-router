#!/usr/bin/env python
"""Benchmark routing-decision latency locally, without invoking any model or requiring
AWS credentials (Phase 9).

This measures exactly what `RouteEvaluationService.evaluate()` costs on its own: policy
resolution, candidate filtering, cost/token estimation, and strategy selection -- all
in-memory, all within this project's control. It deliberately does not measure a real
Bedrock `InvokeModel`/`Converse` call, since that latency is dominated by the model
provider's own inference time and network round trip, not by this router -- benchmarking
it here would produce a number that says more about AWS than about this project. See
`docs/performance/routing-benchmark.md` for the full report and how to interpret it.

Usage:
    python scripts/benchmark_routing.py --iterations 5000
    python scripts/benchmark_routing.py --iterations 5000 --request scripts/examples/support_assistant_balanced.json
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.requests import InferenceRequest
from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator

DEFAULT_REQUEST_PATH = Path("scripts/examples/support_assistant_balanced.json")


def build_service(policies_dir: Path) -> RouteEvaluationService:
    catalogue = LocalFileModelCatalogue(policies_dir / "model_catalogue.yaml")
    policy_repository = LocalFileRoutingPolicyRepository(
        applications_dir=policies_dir / "applications",
        default_policy_path=policies_dir / "default_policy.yaml",
    )
    return RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=SystemClock(),
        identifier_generator=Uuid4IdentifierGenerator(),
    )


def percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    index = min(len(sorted_samples) - 1, int(len(sorted_samples) * pct))
    return sorted_samples[index]


def run_benchmark(
    service: RouteEvaluationService, request: InferenceRequest, iterations: int, warmup: int
) -> list[float]:
    for _ in range(warmup):
        service.evaluate(request)

    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        service.evaluate(request)
        samples_ms.append((time.perf_counter() - started) * 1000)
    return samples_ms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request",
        type=Path,
        default=DEFAULT_REQUEST_PATH,
        help="Path to a JSON InferenceRequest payload to route repeatedly",
    )
    parser.add_argument(
        "--policies-dir",
        type=Path,
        default=Path("policies"),
        help="Directory containing model_catalogue.yaml, default_policy.yaml, and applications/",
    )
    parser.add_argument(
        "--iterations", type=int, default=2000, help="Number of routing decisions to time"
    )
    parser.add_argument(
        "--warmup", type=int, default=100, help="Untimed warmup iterations before measuring"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON instead of a table"
    )
    args = parser.parse_args(argv)

    request_data = json.loads(args.request.read_text(encoding="utf-8"))
    request = InferenceRequest.model_validate(request_data)
    service = build_service(args.policies_dir)

    samples_ms = run_benchmark(service, request, args.iterations, args.warmup)
    sorted_samples = sorted(samples_ms)

    stats = {
        "iterations": args.iterations,
        "min_ms": round(min(sorted_samples), 4),
        "mean_ms": round(statistics.fmean(sorted_samples), 4),
        "median_ms": round(statistics.median(sorted_samples), 4),
        "p95_ms": round(percentile(sorted_samples, 0.95), 4),
        "p99_ms": round(percentile(sorted_samples, 0.99), 4),
        "max_ms": round(max(sorted_samples), 4),
        "throughput_per_sec": round(1000 / statistics.fmean(sorted_samples), 1),
    }

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(
            f"Routing-decision latency over {stats['iterations']} iterations (in-process, no AWS calls):"
        )
        print(f"  min:    {stats['min_ms']:>8} ms")
        print(f"  median: {stats['median_ms']:>8} ms")
        print(f"  mean:   {stats['mean_ms']:>8} ms")
        print(f"  p95:    {stats['p95_ms']:>8} ms")
        print(f"  p99:    {stats['p99_ms']:>8} ms")
        print(f"  max:    {stats['max_ms']:>8} ms")
        print(f"  throughput: ~{stats['throughput_per_sec']}/sec single-threaded")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
