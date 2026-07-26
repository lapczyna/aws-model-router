#!/usr/bin/env python
"""Evaluate a routing decision locally, without invoking any model or AWS credentials.

Usage:
    python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json

The request file is JSON matching `domain.requests.InferenceRequest` (snake_case field
names — this is the internal request shape, distinct from the camelCase HTTP API
contract documented in docs/architecture/api-contracts.md, which a Lambda handler will
translate to/from starting in Phase 5).

Requires `pip install -e ".[dev]"` (see README.md) so `domain`/`application`/`adapters`/
`shared` are importable.
"""

import argparse
import json
import sys
from pathlib import Path

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.errors import ConfigurationError, RoutingPolicyNotFoundError
from domain.requests import InferenceRequest
from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", type=Path, required=True, help="Path to a JSON InferenceRequest payload"
    )
    parser.add_argument(
        "--policies-dir",
        type=Path,
        default=Path("policies"),
        help="Directory containing model_catalogue.yaml, default_policy.yaml, and applications/",
    )
    args = parser.parse_args(argv)

    request_data = json.loads(args.request.read_text(encoding="utf-8"))
    request = InferenceRequest.model_validate(request_data)
    service = build_service(args.policies_dir)

    try:
        decision = service.evaluate(request)
    except RoutingPolicyNotFoundError as exc:
        print(json.dumps({"error": "NO_ROUTING_POLICY", "message": str(exc)}), file=sys.stderr)
        return 1
    except ConfigurationError as exc:
        print(json.dumps({"error": "INVALID_CONFIGURATION", "message": str(exc)}), file=sys.stderr)
        return 1

    print(decision.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
