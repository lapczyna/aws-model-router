#!/usr/bin/env python
"""Compare estimated cost across every catalogued model for a set of representative
workloads (Phase 9), without requiring AWS credentials or making any Bedrock call.

Every figure this script prints is this router's own *estimate*
(`domain.cost_estimation.DefaultCostEstimator`/`DefaultTokenEstimator`) -- the same
deterministic, character-count-based heuristic used at request time, not real AWS
billing. See docs/cost/cost-estimation-guide.md for why the estimate diverges from
actual billed cost, and docs/cost/cost-comparison-report.md for the full report this
script generates.

Usage:
    python scripts/cost_comparison_report.py
    python scripts/cost_comparison_report.py --requests-per-day 10000
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from domain.catalogue import ModelDefinition
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import Role
from domain.messages import Message


@dataclass(frozen=True)
class Workload:
    name: str
    description: str
    input_chars: int
    maximum_output_tokens: int


WORKLOADS = (
    Workload(
        "short-chat-turn",
        "A brief conversational exchange (e.g. a support chatbot reply)",
        input_chars=200,
        maximum_output_tokens=200,
    ),
    Workload(
        "document-summary",
        "Summarizing a medium-length document (a few paragraphs of input)",
        input_chars=4000,
        maximum_output_tokens=500,
    ),
    Workload(
        "long-document-analysis",
        "Analyzing a long document (e.g. a multi-page report)",
        input_chars=40000,
        maximum_output_tokens=1500,
    ),
)


def estimate_cost_usd(
    model: ModelDefinition, workload: Workload, token_estimator: DefaultTokenEstimator
) -> float:
    messages = [Message(role=Role.USER, content="x" * workload.input_chars)]
    usage = token_estimator.estimate(messages, workload.maximum_output_tokens)
    estimated = DefaultCostEstimator().estimate(usage, model.pricing)
    return float(estimated.amount_usd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=Path("policies/model_catalogue.yaml"),
        help="Path to model_catalogue.yaml",
    )
    parser.add_argument(
        "--requests-per-day",
        type=int,
        default=10_000,
        help="Requests/day used for the monthly-cost projection",
    )
    args = parser.parse_args(argv)

    catalogue = LocalFileModelCatalogue(args.catalogue)
    models = catalogue.all_models()
    token_estimator = DefaultTokenEstimator()

    for workload in WORKLOADS:
        print(f"\n=== {workload.name} — {workload.description} ===")
        print(
            f"    (~{workload.input_chars} input chars, "
            f"{workload.maximum_output_tokens} max output tokens)"
        )
        rows = [
            (model.model_alias, estimate_cost_usd(model, workload, token_estimator))
            for model in models
        ]
        cheapest = min(cost for _, cost in rows)
        for alias, cost in sorted(rows, key=lambda r: r[1]):
            multiple = cost / cheapest if cheapest > 0 else float("inf")
            monthly = cost * args.requests_per_day * 30
            print(
                f"    {alias:<28} ${cost:>10.6f}/request  "
                f"({multiple:>5.1f}x cheapest)  ~${monthly:>10.2f}/month "
                f"@ {args.requests_per_day:,}/day"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
