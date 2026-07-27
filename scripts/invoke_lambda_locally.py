#!/usr/bin/env python
"""Invoke the real Lambda handler code (`handlers.api_handler`) against a synthetic API
Gateway proxy event, without deploying anything.

Two modes:

  Fake mode (default) — no AWS credentials required. Builds `HandlerServices` from the
  bundled `policies/` catalogue/policies (same as `scripts/evaluate_route.py`) plus a
  deterministic, in-process `EchoModelProvider` and in-memory idempotency/decision
  stores. This exercises the actual request parsing, routing, error mapping, and response
  serialization code in `src/handlers/`, end to end — just never calls a real model.

  Real mode (--use-real-services) — calls `handlers.api_handler.build_services()`, the
  same function the deployed Lambda uses. Requires real AWS credentials and the
  `DECISIONS_TABLE_NAME` / `IDEMPOTENCY_TABLE_NAME` environment variables (see the
  `cdk deploy` outputs, or `docs/operations/deployment-and-teardown.md`). `POST
  /v1/inference` in this mode makes a real, billable Bedrock call, so it additionally
  requires --confirm-cost — the other five routes never invoke a model.

Usage:
    # Fake mode: route evaluation (never invokes a model in either mode)
    python scripts/invoke_lambda_locally.py --method POST --resource /v1/routes/evaluate \
        --body events/support_assistant_balanced.json

    # Fake mode: inference, via the deterministic EchoModelProvider
    python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
        --body events/support_assistant_balanced.json

    # Fake mode: list models
    python scripts/invoke_lambda_locally.py --method GET --resource /v1/models

    # Real mode against a deployed dev stack
    export DECISIONS_TABLE_NAME=ModelRouter-dev-...
    export IDEMPOTENCY_TABLE_NAME=ModelRouter-dev-...
    python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
        --body events/support_assistant_balanced.json \
        --use-real-services --confirm-cost

Requires `pip install -e ".[dev]"` (see README.md) so `domain`/`application`/`adapters`/
`handlers`/`shared` are importable.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository
from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ProviderName, Role, StopReason
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse
from domain.usage import Usage
from handlers.api_handler import HandlerServices, dispatch
from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator

_MODEL_INVOKING_ROUTE = ("POST", "/v1/inference")


class EchoModelProvider:
    """A deterministic, in-process `ModelProvider` fake: never makes a network call, so
    fake mode can exercise `POST /v1/inference` end to end (including the idempotency
    and decision-repository paths) without any AWS credentials. The response text is
    intentionally NOT a real model's answer — it just echoes back what was sent, so it's
    obvious this isn't a real inference result.
    """

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        last_message = request.messages[-1].content
        echoed = f"[echo mode — not a real model response] You said: {last_message!r}"
        return ProviderResponse(
            model_alias=request.model_alias,
            provider=ProviderName.BEDROCK,
            message=Message(role=Role.ASSISTANT, content=echoed),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=len(last_message.split()), output_tokens=len(echoed.split())),
        )


def build_fake_services(policies_dir: Path) -> HandlerServices:
    catalogue = LocalFileModelCatalogue(policies_dir / "model_catalogue.yaml")
    policy_repository = LocalFileRoutingPolicyRepository(
        applications_dir=policies_dir / "applications",
        default_policy_path=policies_dir / "default_policy.yaml",
    )
    clock = SystemClock()
    identifier_generator = Uuid4IdentifierGenerator()

    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=identifier_generator,
    )
    decision_repository = InMemoryRoutingDecisionRepository()
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=EchoModelProvider(),
        clock=clock,
        identifier_generator=identifier_generator,
        idempotency_store=InMemoryIdempotencyStore(clock=clock),
        decision_repository=decision_repository,
    )
    return HandlerServices(
        catalogue=catalogue,
        route_service=route_service,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
    )


def build_event(
    method: str,
    resource: str,
    *,
    body: dict[str, Any] | None,
    path_parameters: dict[str, str] | None,
    query_string_parameters: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "httpMethod": method,
        "resource": resource,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "pathParameters": path_parameters,
        "queryStringParameters": query_string_parameters,
        "requestContext": {"requestId": f"local-{uuid.uuid4()}"},
    }


def _parse_key_value_pairs(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--method", required=True, help='HTTP method, e.g. "GET" or "POST"')
    parser.add_argument(
        "--resource",
        required=True,
        help="API Gateway resource path, e.g. /v1/inference or /v1/decisions/{decisionId}",
    )
    parser.add_argument("--body", type=Path, help="Path to a JSON request body (camelCase)")
    parser.add_argument(
        "--path-param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable. E.g. --path-param decisionId=dec_123",
    )
    parser.add_argument(
        "--query-param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable. E.g. --query-param applicationId=support-assistant",
    )
    parser.add_argument(
        "--policies-dir",
        type=Path,
        default=Path("policies"),
        help="Directory containing model_catalogue.yaml, default_policy.yaml, and applications/ "
        "(fake mode only)",
    )
    parser.add_argument(
        "--use-real-services",
        action="store_true",
        help="Call handlers.api_handler.build_services() instead of fakes — requires real AWS "
        "credentials and DECISIONS_TABLE_NAME/IDEMPOTENCY_TABLE_NAME environment variables",
    )
    parser.add_argument(
        "--confirm-cost",
        action="store_true",
        help="Required alongside --use-real-services for POST /v1/inference — acknowledges this "
        "makes a real, billable Bedrock call",
    )
    args = parser.parse_args(argv)

    if (
        args.use_real_services
        and (args.method, args.resource) == _MODEL_INVOKING_ROUTE
        and not args.confirm_cost
    ):
        print(
            "*** --use-real-services with POST /v1/inference makes a REAL, billable Bedrock "
            "call. Re-run with --confirm-cost once you accept this. ***",
            file=sys.stderr,
        )
        return 1

    body = json.loads(args.body.read_text(encoding="utf-8")) if args.body else None
    event = build_event(
        args.method,
        args.resource,
        body=body,
        path_parameters=_parse_key_value_pairs(args.path_param) or None,
        query_string_parameters=_parse_key_value_pairs(args.query_param) or None,
    )

    if args.use_real_services:
        from handlers.api_handler import build_services

        services = build_services()
    else:
        services = build_fake_services(args.policies_dir)

    response = dispatch(event, services)
    print(json.dumps(json.loads(response["body"]), indent=2))
    print(f"# statusCode={response['statusCode']}", file=sys.stderr)
    return 0 if response["statusCode"] < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
