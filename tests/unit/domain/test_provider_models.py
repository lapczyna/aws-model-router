import pytest
from pydantic import ValidationError

from domain.enums import ProviderName, Role, StopReason
from domain.messages import Message
from domain.provider import ProviderRequest, ProviderResponse
from domain.usage import Usage

pytestmark = pytest.mark.unit


def test_provider_request_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        ProviderRequest(model_alias="model-a", messages=(), max_output_tokens=100)


def test_provider_request_rejects_temperature_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        ProviderRequest(
            model_alias="model-a",
            messages=(Message(role=Role.USER, content="hi"),),
            max_output_tokens=100,
            temperature=1.5,
        )


def test_provider_request_accepts_valid_optional_fields() -> None:
    request = ProviderRequest(
        model_alias="model-a",
        messages=(Message(role=Role.USER, content="hi"),),
        max_output_tokens=100,
        system_prompt="be helpful",
        temperature=0.5,
        top_p=0.9,
        requires_tool_use=True,
    )
    assert request.system_prompt == "be helpful"
    assert request.requires_tool_use is True


def test_provider_response_round_trips() -> None:
    response = ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hello"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=20),
    )
    assert response.stop_reason is StopReason.END_TURN
    assert response.usage.input_tokens == 10


def test_provider_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(
            {
                "model_alias": "model-a",
                "messages": [{"role": "user", "content": "hi"}],
                "max_output_tokens": 100,
                "unexpected": "nope",
            }
        )
