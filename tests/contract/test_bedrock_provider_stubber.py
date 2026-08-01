"""Contract tests for `BedrockModelProvider` using a real boto3 client wrapped in
`botocore.stub.Stubber` — validates our request/response shapes against botocore's own
Bedrock Runtime service model, complementing the hand-rolled-fake unit tests in
`tests/unit/adapters/bedrock/test_bedrock_model_provider.py`.

No network call is made: `Stubber` intercepts before any HTTP request is sent, and
dummy credentials below ensure no real AWS credential chain is consulted either.
"""

import boto3
import pytest
from botocore.stub import Stubber

from adapters.bedrock.bedrock_model_provider import BedrockModelProvider
from adapters.common.retry import RetryPolicy
from domain.enums import ProviderErrorCategory, Role
from domain.errors import ProviderError
from domain.messages import Message
from domain.provider import ProviderRequest
from tests.support.fakes import InMemoryModelCatalogue, make_model

pytestmark = pytest.mark.contract


def _client():
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_session_token="testing",
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        model_alias="balanced-text-primary",
        messages=(Message(role=Role.USER, content="Summarize this incident report."),),
        max_output_tokens=100,
    )


def test_successful_invocation_matches_bedrock_service_model() -> None:
    client = _client()
    stubber = Stubber(client)
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))

    service_response = {
        "output": {"message": {"role": "assistant", "content": [{"text": "Summary: all clear."}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 15, "outputTokens": 5, "totalTokens": 20},
        "metrics": {"latencyMs": 250},
    }
    expected_params = {
        "modelId": model.resolution.value,
        "messages": [{"role": "user", "content": [{"text": "Summarize this incident report."}]}],
        "inferenceConfig": {"maxTokens": 100},
    }
    stubber.add_response("converse", service_response, expected_params)
    stubber.activate()

    provider = BedrockModelProvider(client=client, model_catalogue=InMemoryModelCatalogue([model]))
    response = provider.invoke(_request())

    stubber.assert_no_pending_responses()
    assert response.message.content == "Summary: all clear."
    assert response.usage.input_tokens == 15
    assert response.usage.output_tokens == 5


def test_throttling_exception_via_stubber_exhausts_retries() -> None:
    client = _client()
    stubber = Stubber(client)
    model = make_model("balanced-text-primary", capability_tags=("balanced-text",))

    for _ in range(3):
        stubber.add_client_error(
            "converse",
            service_error_code="ThrottlingException",
            service_message="Too many requests, please wait and try again.",
            http_status_code=429,
        )
    stubber.activate()

    provider = BedrockModelProvider(
        client=client,
        model_catalogue=InMemoryModelCatalogue([model]),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.invoke(_request())

    assert exc_info.value.category is ProviderErrorCategory.THROTTLED
    stubber.assert_no_pending_responses()
