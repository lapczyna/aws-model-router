import pytest

from domain.enums import Role
from domain.idempotency import IdempotencyOutcome, IdempotencyReservation, compute_request_hash
from domain.messages import Message
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements

pytestmark = pytest.mark.unit


def _request(content: str = "hello", **overrides: object) -> InferenceRequest:
    defaults: dict[str, object] = {
        "application_id": "app-1",
        "messages": (Message(role=Role.USER, content=content),),
        "requirements": RoutingRequirements(capability="balanced-text"),
    }
    defaults.update(overrides)
    return InferenceRequest.model_validate(defaults)


def test_hash_is_deterministic_for_identical_requests() -> None:
    first = compute_request_hash(_request())
    second = compute_request_hash(_request())
    assert first == second


def test_hash_differs_for_different_message_content() -> None:
    first = compute_request_hash(_request(content="hello"))
    second = compute_request_hash(_request(content="goodbye"))
    assert first != second


def test_hash_differs_for_different_application_id() -> None:
    first = compute_request_hash(_request(application_id="app-1"))
    second = compute_request_hash(_request(application_id="app-2"))
    assert first != second


def test_hash_differs_for_different_requirements() -> None:
    first = compute_request_hash(
        _request(requirements=RoutingRequirements(capability="balanced-text"))
    )
    second = compute_request_hash(
        _request(requirements=RoutingRequirements(capability="economical-text"))
    )
    assert first != second


def test_hash_is_unaffected_by_conversation_id_and_metadata() -> None:
    first = compute_request_hash(_request(conversation_id="conv-1", metadata={"a": "1"}))
    second = compute_request_hash(_request(conversation_id="conv-2", metadata={"a": "2"}))
    assert first == second


def test_reservation_defaults_to_no_cached_result() -> None:
    reservation = IdempotencyReservation(outcome=IdempotencyOutcome.NEW)
    assert reservation.cached_result is None
