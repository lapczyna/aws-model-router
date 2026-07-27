"""Abuse-case tests for `docs/security/threat-model.md`: adversarial or malformed input
exercised through the real dispatch/orchestrator path, verifying the documented
mitigation actually holds — not just that the "happy path" works.
"""

import io
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ProviderName, Role, StopReason
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.usage import Usage
from handlers.api_handler import HandlerServices, dispatch
from handlers.request_mapping import parse_inference_request
from shared.structured_logging import JsonFormatter
from tests.support.fakes import (
    FixedClock,
    InMemoryModelCatalogue,
    InMemoryRoutingPolicyRepository,
    SequentialIdentifierGenerator,
    make_model,
    make_policy,
)

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_SENTINEL_PROMPT = "SENTINEL-RAW-PROMPT-CONTENT-must-never-be-logged-or-persisted"


class _EchoModelProvider:
    """Echoes the sentinel content back in the response, so both the request and the
    response side of a data-leakage abuse case can be exercised in one round trip.
    """

    def invoke(self, request: Any) -> ProviderResponse:
        return ProviderResponse(
            model_alias=request.model_alias,
            provider=ProviderName.BEDROCK,
            message=Message(role=Role.ASSISTANT, content=f"echo: {request.messages[-1].content}"),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=5, output_tokens=5),
        )


def _services(decision_repository: Any) -> HandlerServices:
    model = make_model("model-a", capability_tags=("balanced-text",))
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    catalogue = InMemoryModelCatalogue([model])
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    clock = FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=SequentialIdentifierGenerator(),
    )
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=_EchoModelProvider(),
        clock=clock,
        identifier_generator=SequentialIdentifierGenerator(),
        decision_repository=decision_repository,
        monotonic=lambda: 0.0,
    )
    return HandlerServices(
        catalogue=catalogue,
        route_service=route_service,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
    )


def _event(body: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    event = {
        "httpMethod": "POST",
        "resource": "/v1/inference",
        "body": json.dumps(body),
        "isBase64Encoded": False,
        "pathParameters": None,
        "queryStringParameters": None,
        "requestContext": {
            "requestId": "req-1",
            "identity": {"userArn": "arn:aws:iam::123456789012:role/caller-role"},
        },
    }
    event.update(overrides)
    return event


# --- T5: unrecognized fields are ignored, never able to influence routing -----------


def test_unrecognized_field_has_no_effect_on_parsed_request() -> None:
    body = {
        "applicationId": "app-1",
        "messages": [{"role": "user", "content": "hi"}],
        "requirements": {"capability": "balanced-text"},
        "modelId": "arn:aws:bedrock:us-east-1::foundation-model/attacker-chosen-model",
    }
    request = parse_inference_request(body)

    assert not hasattr(request, "modelId")
    assert not hasattr(request, "model_id")
    # Confirms the field is genuinely absent, not merely inaccessible under a different
    # name — InferenceRequest's own extra="forbid" would reject it if it were ever
    # passed to the constructor at all, which it is not (see the corrected
    # threat-model.md T5 entry: this is field-extraction allowlisting, not
    # constructor-level rejection).


def test_unrecognized_field_does_not_change_the_selected_model() -> None:
    decision_repository = InMemoryRoutingDecisionRepository()
    services = _services(decision_repository)
    body = {
        "applicationId": "app-1",
        "messages": [{"role": "user", "content": "hi"}],
        "requirements": {"capability": "balanced-text"},
        "modelId": "arn:aws:bedrock:us-east-1::foundation-model/attacker-chosen-model",
    }

    response = dispatch(_event(body), services)

    assert response["statusCode"] == 200
    parsed = json.loads(response["body"])
    assert parsed["route"]["modelAlias"] == "model-a"  # policy's real model, not the smuggled one


# --- T10: raw prompt/response content never appears in logs or persisted records ----


def test_sentinel_prompt_never_appears_in_the_persisted_audit_record() -> None:
    decision_repository = InMemoryRoutingDecisionRepository()
    services = _services(decision_repository)
    body = {
        "applicationId": "app-1",
        "messages": [{"role": "user", "content": _SENTINEL_PROMPT}],
        "requirements": {"capability": "balanced-text"},
    }

    response = dispatch(_event(body), services)
    decision_id = json.loads(response["body"])["decisionId"]

    stored = decision_repository.get(decision_id)
    assert stored is not None
    assert _SENTINEL_PROMPT not in stored.model_dump_json()


def test_sentinel_prompt_never_appears_in_structured_logs() -> None:
    logger = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    original_handlers = logger.handlers
    logger.handlers = [handler]
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        decision_repository = InMemoryRoutingDecisionRepository()
        services = _services(decision_repository)
        body = {
            "applicationId": "app-1",
            "messages": [{"role": "user", "content": _SENTINEL_PROMPT}],
            "requirements": {"capability": "balanced-text"},
        }
        dispatch(_event(body), services)
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)

    assert _SENTINEL_PROMPT not in stream.getvalue()


# --- caller_principal_arn detective control (threat model T2) -----------------------


def test_caller_principal_arn_is_logged_for_every_request() -> None:
    logger = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    original_handlers = logger.handlers
    logger.handlers = [handler]
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        services = _services(InMemoryRoutingDecisionRepository())
        dispatch(_event({"applicationId": "app-1"}), services)  # malformed — still logs completion
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    completed = [line for line in lines if line["message"] == "Request completed"]
    assert len(completed) == 1
    assert completed[0]["caller_principal_arn"] == "arn:aws:iam::123456789012:role/caller-role"


def test_caller_principal_arn_is_none_when_unauthenticated() -> None:
    logger = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    original_handlers = logger.handlers
    logger.handlers = [handler]
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        services = _services(InMemoryRoutingDecisionRepository())
        event = _event({}, resource="/health", httpMethod="GET")
        event["requestContext"] = {"requestId": "req-1"}  # no "identity" — unauthenticated route
        dispatch(event, services)
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    completed = [line for line in lines if line["message"] == "Request completed"]
    assert completed[0]["caller_principal_arn"] == "none"


# --- Decision lookup with adversarial path input never 500s -------------------------


@pytest.mark.parametrize(
    "decision_id",
    [
        "'; DROP TABLE decisions; --",
        "../../etc/passwd",
        "<script>alert(1)</script>",
        "x" * 10_000,
    ],
)
def test_decision_lookup_with_adversarial_id_returns_404_not_500(decision_id: str) -> None:
    services = _services(InMemoryRoutingDecisionRepository())
    event = {
        "httpMethod": "GET",
        "resource": "/v1/decisions/{decisionId}",
        "body": None,
        "isBase64Encoded": False,
        "pathParameters": {"decisionId": decision_id},
        "queryStringParameters": {"applicationId": "app-1"},
        "requestContext": {"requestId": "req-1"},
    }

    response = dispatch(event, services)

    assert response["statusCode"] == 404
    assert json.loads(response["body"])["errorCode"] == "NOT_FOUND"
