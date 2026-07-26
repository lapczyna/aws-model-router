import pytest
from pydantic import ValidationError

from domain.enums import Role
from domain.messages import Message
from domain.requests import InferenceRequest
from domain.requirements import RoutingRequirements

pytestmark = pytest.mark.unit


def test_message_requires_valid_role() -> None:
    message = Message(role=Role.USER, content="hello")
    assert message.role is Role.USER
    assert message.content == "hello"

    with pytest.raises(ValidationError):
        Message.model_validate({"role": "not-a-role", "content": "hello"})


def test_inference_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        InferenceRequest(
            application_id="app-1",
            messages=(),
            requirements=RoutingRequirements(capability="balanced-text"),
        )


def test_inference_request_rejects_blank_application_id() -> None:
    with pytest.raises(ValidationError):
        InferenceRequest(
            application_id="   ",
            messages=(Message(role=Role.USER, content="hi"),),
            requirements=RoutingRequirements(capability="balanced-text"),
        )


def test_inference_request_defaults_metadata_to_empty_mapping() -> None:
    request = InferenceRequest(
        application_id="app-1",
        messages=(Message(role=Role.USER, content="hi"),),
        requirements=RoutingRequirements(capability="balanced-text"),
    )
    assert request.metadata == {}
    assert request.conversation_id is None
    assert request.idempotency_key is None


def test_inference_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InferenceRequest.model_validate(
            {
                "application_id": "app-1",
                "messages": [{"role": "user", "content": "hi"}],
                "requirements": {"capability": "balanced-text"},
                "unexpected_field": "nope",
            }
        )
