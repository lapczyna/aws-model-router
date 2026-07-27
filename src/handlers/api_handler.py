"""The single Lambda entry point for the Model Router REST API (ADR-016).

Thin by design (CONTRIBUTING.md): each `_handle_*` function takes the services it needs
as explicit parameters and only parses its event, calls one application service, and
formats the response — no business logic lives here. This also makes every handler
function directly unit-testable with fake adapters (`tests/support/fakes.py`), the same
pattern used throughout `src/application/`, without needing real AWS credentials.

`handler()`, the real Lambda entry point, builds the services once at module import time
(`build_services()`) so a warm execution environment reuses them — the bundled
`policies/` config and the boto3 clients — across invocations instead of rebuilding them
on every request.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from pydantic import ValidationError

from adapters.bedrock.bedrock_model_provider import BedrockModelProvider
from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository
from adapters.dynamodb.dynamodb_decision_repository import DynamoDbRoutingDecisionRepository
from adapters.dynamodb.dynamodb_idempotency_store import DynamoDbIdempotencyStore
from adapters.memory.in_memory_model_health_repository import InMemoryModelHealthRepository
from adapters.metrics.emf_metrics_publisher import EmfMetricsPublisher
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.ports import ModelCatalogue, RoutingDecisionRepository
from handlers.error_mapping import (
    error_response_body,
    map_exception_to_status_and_body,
    map_no_selection_to_status_and_body,
)
from handlers.request_mapping import (
    parse_inference_request,
    parse_json_body,
    serialize_audit_record,
    serialize_inference_result,
    serialize_models_response,
    serialize_route_evaluation,
)
from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator
from shared.structured_logging import configure_logging

logger = logging.getLogger()

_MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(256 * 1024)))


@dataclass(frozen=True)
class HandlerServices:
    catalogue: ModelCatalogue
    route_service: RouteEvaluationService
    orchestrator: InvocationOrchestrator
    decision_repository: RoutingDecisionRepository


def build_services() -> HandlerServices:
    """Wire real (Bedrock/DynamoDB/local-file) adapters. Requires AWS credentials and
    the `DECISIONS_TABLE_NAME`/`IDEMPOTENCY_TABLE_NAME` environment variables — never
    called by unit tests, which construct `HandlerServices` directly with fakes.
    """
    policies_dir = Path(os.environ.get("POLICIES_DIR", "policies"))
    region = os.environ.get("AWS_REGION", "us-east-1")
    environment = os.environ.get("ENVIRONMENT_NAME", "dev")

    catalogue = LocalFileModelCatalogue(policies_dir / "model_catalogue.yaml")
    policy_repository = LocalFileRoutingPolicyRepository(
        applications_dir=policies_dir / "applications",
        default_policy_path=policies_dir / "default_policy.yaml",
    )
    clock = SystemClock()
    identifier_generator = Uuid4IdentifierGenerator()
    model_health_repository = InMemoryModelHealthRepository()

    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=identifier_generator,
        model_health_repository=model_health_repository,
    )

    bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    model_provider = BedrockModelProvider(client=bedrock_client, model_catalogue=catalogue)

    dynamodb = boto3.resource("dynamodb", region_name=region)
    decision_repository = DynamoDbRoutingDecisionRepository(
        table=dynamodb.Table(os.environ["DECISIONS_TABLE_NAME"])
    )
    idempotency_store = DynamoDbIdempotencyStore(
        table=dynamodb.Table(os.environ["IDEMPOTENCY_TABLE_NAME"])
    )

    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider,
        clock=clock,
        identifier_generator=identifier_generator,
        idempotency_store=idempotency_store,
        decision_repository=decision_repository,
        model_health_repository=model_health_repository,
        metrics_publisher=EmfMetricsPublisher(environment=environment),
    )
    return HandlerServices(
        catalogue=catalogue,
        route_service=route_service,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
    )


def _respond(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _extract_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return str(body)


def _request_id(event: dict[str, Any]) -> str:
    return str(event.get("requestContext", {}).get("requestId", "unknown"))


def _parse_body_or_400(
    event: dict[str, Any], request_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Returns `(parsed_body, error_response)` — exactly one is `None`."""
    raw_body = _extract_body(event)
    if len(raw_body.encode("utf-8")) > _MAX_REQUEST_BODY_BYTES:
        return None, _respond(
            400,
            error_response_body(
                request_id, "INVALID_REQUEST", "Request body exceeds the maximum allowed size."
            ),
        )
    try:
        return parse_json_body(raw_body), None
    except (json.JSONDecodeError, TypeError) as exc:
        logger.info(
            "Malformed request body: %s",
            exc,
            extra={"request_id": request_id, "error_code": "INVALID_REQUEST"},
        )
        return None, _respond(
            400,
            error_response_body(request_id, "INVALID_REQUEST", "Request body is not valid JSON."),
        )


def handle_health() -> dict[str, Any]:
    return _respond(200, {"status": "ok"})


def handle_ready(services: HandlerServices) -> dict[str, Any]:
    # Reaching this line at all means service construction (reading the bundled
    # policies/, creating the boto3 clients) already succeeded at cold start — a
    # failure there fails Lambda initialization before any invocation is handled.
    return _respond(
        200, {"status": "ready", "modelCatalogueVersion": services.catalogue.catalogue_version}
    )


def handle_inference(
    event: dict[str, Any], request_id: str, services: HandlerServices
) -> dict[str, Any]:
    body, error = _parse_body_or_400(event, request_id)
    if error is not None:
        return error
    assert body is not None

    try:
        request = parse_inference_request(body)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        logger.info(
            "Invalid inference request: %s",
            exc,
            extra={"request_id": request_id, "error_code": "INVALID_REQUEST"},
        )
        return _respond(
            400, error_response_body(request_id, "INVALID_REQUEST", "Request failed validation.")
        )

    try:
        result = services.orchestrator.invoke(request)
    except Exception as exc:
        status, error_body = map_exception_to_status_and_body(exc, request_id)
        logger.exception(
            "Inference invocation failed",
            extra={
                "request_id": request_id,
                "application_id": request.application_id,
                "capability": request.requirements.capability,
                "error_code": error_body["errorCode"],
                "status_code": status,
            },
        )
        return _respond(status, error_body)

    if result.decision.selected_model_alias is None:
        status, error_body = map_no_selection_to_status_and_body(
            result.decision,
            invocation_attempted=bool(result.invocation_attempts),
            request_id=request_id,
        )
        return _respond(status, error_body)

    return _respond(200, serialize_inference_result(result, request_id))


def handle_routes_evaluate(
    event: dict[str, Any], request_id: str, services: HandlerServices
) -> dict[str, Any]:
    body, error = _parse_body_or_400(event, request_id)
    if error is not None:
        return error
    assert body is not None

    try:
        request = parse_inference_request(body)
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        logger.info(
            "Invalid route-evaluation request: %s",
            exc,
            extra={"request_id": request_id, "error_code": "INVALID_REQUEST"},
        )
        return _respond(
            400, error_response_body(request_id, "INVALID_REQUEST", "Request failed validation.")
        )

    try:
        decision = services.route_service.evaluate(request)
    except Exception as exc:
        status, error_body = map_exception_to_status_and_body(exc, request_id)
        logger.exception(
            "Route evaluation failed",
            extra={
                "request_id": request_id,
                "application_id": request.application_id,
                "capability": request.requirements.capability,
                "error_code": error_body["errorCode"],
                "status_code": status,
            },
        )
        return _respond(status, error_body)

    # Unlike /v1/inference, evaluation never invokes a model, so "no eligible route" is
    # simply part of the explanation, not an error — always 200.
    return _respond(200, serialize_route_evaluation(decision, request_id))


def handle_models(request_id: str, services: HandlerServices) -> dict[str, Any]:
    return _respond(200, serialize_models_response(services.catalogue.all_models(), request_id))


def handle_get_decision(
    event: dict[str, Any], request_id: str, services: HandlerServices
) -> dict[str, Any]:
    decision_id = (event.get("pathParameters") or {}).get("decisionId")
    if not decision_id:
        return _respond(
            400, error_response_body(request_id, "INVALID_REQUEST", "decisionId is required.")
        )

    caller_application_id = (event.get("queryStringParameters") or {}).get("applicationId")

    audit_record = services.decision_repository.get(decision_id)
    if audit_record is None:
        return _respond(
            404, error_response_body(request_id, "NOT_FOUND", "No such routing decision.")
        )
    if caller_application_id != audit_record.decision.application_id:
        return _respond(
            403,
            error_response_body(
                request_id, "POLICY_DENIED", "You are not authorized to view this decision."
            ),
        )

    return _respond(200, serialize_audit_record(audit_record, request_id))


def dispatch(event: dict[str, Any], services: HandlerServices) -> dict[str, Any]:
    """Route an already-parsed API Gateway proxy event to the matching handler.

    Split from `handler()` so tests can call it directly with fake `HandlerServices`,
    without needing real AWS credentials or the Lambda runtime.
    """
    request_id = _request_id(event)
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    log_extra = {
        "request_id": request_id,
        "http_method": method,
        "resource": resource,
    }

    try:
        if (method, resource) == ("GET", "/health"):
            response = handle_health()
        elif (method, resource) == ("GET", "/ready"):
            response = handle_ready(services)
        elif (method, resource) == ("POST", "/v1/inference"):
            response = handle_inference(event, request_id, services)
        elif (method, resource) == ("POST", "/v1/routes/evaluate"):
            response = handle_routes_evaluate(event, request_id, services)
        elif (method, resource) == ("GET", "/v1/models"):
            response = handle_models(request_id, services)
        elif (method, resource) == ("GET", "/v1/decisions/{decisionId}"):
            response = handle_get_decision(event, request_id, services)
        else:
            response = _respond(404, error_response_body(request_id, "NOT_FOUND", "Unknown route."))
    except Exception:
        logger.exception("Unhandled error processing request", extra=log_extra)
        response = _respond(
            500, error_response_body(request_id, "INTERNAL_ERROR", "An unexpected error occurred.")
        )

    logger.info(
        "Request completed",
        extra={**log_extra, "status_code": response["statusCode"]},
    )
    return response


_SERVICES: HandlerServices | None = None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    global _SERVICES
    if _SERVICES is None:
        configure_logging()
        _SERVICES = build_services()
    return dispatch(event, _SERVICES)
