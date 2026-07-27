"""Dispatch-level tests for the single Lambda entry point (ADR-016): every route, and
the cross-cutting error paths (malformed body, oversized body, unknown route, unhandled
exception), exercised through `dispatch()` with `HandlerServices` built from the same
in-memory fakes used by `tests/unit/application/test_invocation_orchestrator.py` — no
real AWS credentials required.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from adapters.memory.in_memory_idempotency_store import InMemoryIdempotencyStore
from application.invocation_orchestrator import InvocationOrchestrator
from application.route_evaluation_service import RouteEvaluationService
from domain.catalogue import ModelDefinition
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import ProviderErrorCategory, ProviderName, QualityTier, Role, StopReason
from domain.errors import ProviderError
from domain.messages import Message
from domain.policy import IdempotencyPolicy
from domain.provider import ProviderResponse
from domain.usage import Usage
from handlers.api_handler import HandlerServices, dispatch
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


class FakeModelProvider:
    def __init__(self, responses: dict[str, list[ProviderResponse | Exception]]) -> None:
        self._responses = {alias: list(items) for alias, items in responses.items()}

    def invoke(self, request: Any) -> ProviderResponse:
        queue = self._responses.get(request.model_alias)
        if not queue:
            raise AssertionError(f"no more responses for {request.model_alias!r}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RaisingModelCatalogue:
    """Simulates an unexpected failure reaching a route with no internal try/except
    (`handle_models`), to exercise `dispatch()`'s outer catch-all -> 500 path."""

    catalogue_version = 1

    def find_by_capability(self, capability: str) -> Sequence[ModelDefinition]:
        raise AssertionError("not used in this test")

    def get_by_alias(self, model_alias: str) -> ModelDefinition | None:
        raise AssertionError("not used in this test")

    def all_models(self) -> Sequence[ModelDefinition]:
        raise RuntimeError("catalogue backend unavailable")


def _response(model_alias: str = "model-a", content: str = "hello there") -> ProviderResponse:
    return ProviderResponse(
        model_alias=model_alias,
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content=content),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=5, output_tokens=5),
    )


def _services(
    *,
    models: Sequence[ModelDefinition] = (),
    policy: Any = None,
    model_provider: Any = None,
    idempotency_store: Any = None,
    decision_repository: Any = None,
    catalogue: Any = None,
) -> HandlerServices:
    effective_catalogue = catalogue if catalogue is not None else InMemoryModelCatalogue(models)
    policy_repository = InMemoryRoutingPolicyRepository(default_policy=policy)
    clock = FixedClock(FIXED_NOW)
    route_service = RouteEvaluationService(
        policy_repository=policy_repository,
        model_catalogue=effective_catalogue,
        token_estimator=DefaultTokenEstimator(),
        cost_estimator=DefaultCostEstimator(),
        clock=clock,
        identifier_generator=SequentialIdentifierGenerator(),
    )
    orchestrator = InvocationOrchestrator(
        route_evaluation_service=route_service,
        policy_repository=policy_repository,
        model_provider=model_provider or FakeModelProvider({}),
        clock=clock,
        identifier_generator=SequentialIdentifierGenerator(),
        idempotency_store=idempotency_store,
        decision_repository=decision_repository,
        monotonic=lambda: 0.0,
    )
    return HandlerServices(
        catalogue=effective_catalogue,
        route_service=route_service,
        orchestrator=orchestrator,
        decision_repository=decision_repository or InMemoryRoutingDecisionRepository(),
    )


def _event(
    method: str,
    resource: str,
    *,
    body: dict[str, Any] | str | None = None,
    path_parameters: dict[str, str] | None = None,
    query_string_parameters: dict[str, str] | None = None,
    request_id: str = "req-1",
    is_base64_encoded: bool = False,
) -> dict[str, Any]:
    if isinstance(body, dict):
        raw_body: str | None = json.dumps(body)
    else:
        raw_body = body
    return {
        "httpMethod": method,
        "resource": resource,
        "body": raw_body,
        "isBase64Encoded": is_base64_encoded,
        "pathParameters": path_parameters,
        "queryStringParameters": query_string_parameters,
        "requestContext": {"requestId": request_id},
    }


def _inference_body(
    application_id: str = "app-1", idempotency_key: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "applicationId": application_id,
        "messages": [{"role": "user", "content": "hello"}],
        "requirements": {"capability": "balanced-text"},
    }
    if idempotency_key is not None:
        body["idempotencyKey"] = idempotency_key
    return body


def test_health_route() -> None:
    response = dispatch(_event("GET", "/health"), _services())
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_ready_route() -> None:
    model = make_model("model-a")
    response = dispatch(_event("GET", "/ready"), _services(models=[model]))
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "ready"
    assert body["modelCatalogueVersion"] == 1


def test_inference_route_success() -> None:
    model = make_model("model-a")
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    services = _services(models=[model], policy=policy, model_provider=provider)

    response = dispatch(_event("POST", "/v1/inference", body=_inference_body()), services)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["response"] == {"role": "assistant", "content": "hello there"}


def test_inference_route_malformed_json_returns_400() -> None:
    response = dispatch(_event("POST", "/v1/inference", body="{not valid json"), _services())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["errorCode"] == "INVALID_REQUEST"


def test_inference_route_oversized_body_returns_400() -> None:
    huge_body = "x" * (256 * 1024 + 1)
    response = dispatch(_event("POST", "/v1/inference", body=huge_body), _services())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["errorCode"] == "INVALID_REQUEST"


def test_inference_route_missing_field_returns_400() -> None:
    body = {"messages": [{"role": "user", "content": "hi"}], "requirements": {"capability": "x"}}
    response = dispatch(_event("POST", "/v1/inference", body=body), _services())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["errorCode"] == "INVALID_REQUEST"


def test_inference_route_required_capability_unavailable_returns_422() -> None:
    policy = make_policy(allowed_capabilities=("other-capability",))
    response = dispatch(
        _event("POST", "/v1/inference", body=_inference_body()), _services(policy=policy)
    )
    assert response["statusCode"] == 422
    assert json.loads(response["body"])["errorCode"] == "REQUIRED_CAPABILITY_UNAVAILABLE"


def test_inference_route_no_eligible_model_returns_404() -> None:
    model = make_model("model-a", quality_tier=QualityTier.PREMIUM)
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        allowed_quality_tiers=(QualityTier.STANDARD,),
        routing_strategy="lowest_cost",
        preferred_model_alias=None,
    )
    response = dispatch(
        _event("POST", "/v1/inference", body=_inference_body()),
        _services(models=[model], policy=policy),
    )
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["errorCode"] == "NO_ELIGIBLE_MODEL"


def test_inference_route_all_candidates_exhausted_returns_502() -> None:
    model = make_model("model-a")
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider(
        {"model-a": [ProviderError("down", category=ProviderErrorCategory.PERMANENT)]}
    )
    services = _services(models=[model], policy=policy, model_provider=provider)

    response = dispatch(_event("POST", "/v1/inference", body=_inference_body()), services)

    assert response["statusCode"] == 502
    assert json.loads(response["body"])["errorCode"] == "PROVIDER_UNAVAILABLE"


def test_inference_route_idempotency_conflict_returns_409() -> None:
    model = make_model("model-a")
    policy = make_policy(
        allowed_model_aliases=("model-a",),
        preferred_model_alias="model-a",
        idempotency_policy=IdempotencyPolicy(allow_response_caching=True, retention_seconds=300),
    )
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    store = InMemoryIdempotencyStore(clock=FixedClock(FIXED_NOW))
    services = _services(
        models=[model], policy=policy, model_provider=provider, idempotency_store=store
    )

    body = _inference_body(idempotency_key="key-1")
    dispatch(_event("POST", "/v1/inference", body=body), services)
    body_conflict = {**body, "messages": [{"role": "user", "content": "different content"}]}
    response = dispatch(_event("POST", "/v1/inference", body=body_conflict), services)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["errorCode"] == "IDEMPOTENCY_CONFLICT"


def test_routes_evaluate_returns_200_even_when_no_eligible_model() -> None:
    policy = make_policy(allowed_capabilities=("other-capability",))
    response = dispatch(
        _event("POST", "/v1/routes/evaluate", body=_inference_body()), _services(policy=policy)
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["route"]["modelAlias"] is None


def test_routes_evaluate_malformed_json_returns_400() -> None:
    response = dispatch(_event("POST", "/v1/routes/evaluate", body="not json"), _services())
    assert response["statusCode"] == 400


def test_models_route() -> None:
    model = make_model("model-a", capability_tags=("balanced-text",))
    response = dispatch(_event("GET", "/v1/models"), _services(models=[model]))
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["capabilities"][0]["capability"] == "balanced-text"


def test_get_decision_route_success() -> None:
    model = make_model("model-a")
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    decision_repository = InMemoryRoutingDecisionRepository()
    services = _services(
        models=[model],
        policy=policy,
        model_provider=provider,
        decision_repository=decision_repository,
    )
    invoked = dispatch(_event("POST", "/v1/inference", body=_inference_body()), services)
    decision_id = json.loads(invoked["body"])["decisionId"]

    response = dispatch(
        _event(
            "GET",
            "/v1/decisions/{decisionId}",
            path_parameters={"decisionId": decision_id},
            query_string_parameters={"applicationId": "app-1"},
        ),
        services,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["decisionId"] == decision_id


def test_get_decision_route_missing_decision_id_returns_400() -> None:
    response = dispatch(
        _event("GET", "/v1/decisions/{decisionId}", path_parameters=None), _services()
    )
    assert response["statusCode"] == 400


def test_get_decision_route_not_found_returns_404() -> None:
    response = dispatch(
        _event(
            "GET",
            "/v1/decisions/{decisionId}",
            path_parameters={"decisionId": "does-not-exist"},
            query_string_parameters={"applicationId": "app-1"},
        ),
        _services(),
    )
    assert response["statusCode"] == 404


def test_get_decision_route_wrong_owner_returns_403() -> None:
    model = make_model("model-a")
    policy = make_policy(allowed_model_aliases=("model-a",), preferred_model_alias="model-a")
    provider = FakeModelProvider({"model-a": [_response("model-a")]})
    decision_repository = InMemoryRoutingDecisionRepository()
    services = _services(
        models=[model],
        policy=policy,
        model_provider=provider,
        decision_repository=decision_repository,
    )
    invoked = dispatch(_event("POST", "/v1/inference", body=_inference_body()), services)
    decision_id = json.loads(invoked["body"])["decisionId"]

    response = dispatch(
        _event(
            "GET",
            "/v1/decisions/{decisionId}",
            path_parameters={"decisionId": decision_id},
            query_string_parameters={"applicationId": "someone-else"},
        ),
        services,
    )

    assert response["statusCode"] == 403


def test_unknown_route_returns_404() -> None:
    response = dispatch(_event("DELETE", "/v1/unknown"), _services())
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["errorCode"] == "NOT_FOUND"


def test_unhandled_exception_returns_500() -> None:
    response = dispatch(_event("GET", "/v1/models"), _services(catalogue=RaisingModelCatalogue()))
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["errorCode"] == "INTERNAL_ERROR"
