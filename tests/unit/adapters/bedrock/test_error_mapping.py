import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from adapters.bedrock.error_mapping import (
    classify_client_error,
    classify_provider_exception,
    safe_message_for,
)
from domain.enums import ProviderErrorCategory

pytestmark = pytest.mark.unit


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "irrelevant"}}, "Converse")


@pytest.mark.parametrize("code", ["ThrottlingException", "TooManyRequestsException"])
def test_throttled_codes(code: str) -> None:
    assert classify_client_error(_client_error(code)) is ProviderErrorCategory.THROTTLED


def test_model_timeout_code_is_timeout() -> None:
    assert (
        classify_client_error(_client_error("ModelTimeoutException"))
        is ProviderErrorCategory.TIMEOUT
    )


@pytest.mark.parametrize(
    "code", ["ServiceUnavailableException", "InternalServerException", "ModelNotReadyException"]
)
def test_transient_codes(code: str) -> None:
    assert classify_client_error(_client_error(code)) is ProviderErrorCategory.TRANSIENT


@pytest.mark.parametrize(
    "code", ["ValidationException", "AccessDeniedException", "ResourceNotFoundException"]
)
def test_permanent_codes(code: str) -> None:
    assert classify_client_error(_client_error(code)) is ProviderErrorCategory.PERMANENT


def test_unknown_client_error_code_defaults_to_permanent() -> None:
    assert (
        classify_client_error(_client_error("SomethingNewAWSAdded"))
        is ProviderErrorCategory.PERMANENT
    )


def test_connect_timeout_is_timeout() -> None:
    exc = ConnectTimeoutError(endpoint_url="https://example.invalid")
    assert classify_provider_exception(exc) is ProviderErrorCategory.TIMEOUT


def test_read_timeout_is_timeout() -> None:
    exc = ReadTimeoutError(endpoint_url="https://example.invalid")
    assert classify_provider_exception(exc) is ProviderErrorCategory.TIMEOUT


def test_endpoint_connection_error_is_transient() -> None:
    exc = EndpointConnectionError(endpoint_url="https://example.invalid")
    assert classify_provider_exception(exc) is ProviderErrorCategory.TRANSIENT


def test_unrecognized_exception_type_defaults_to_permanent() -> None:
    assert classify_provider_exception(ValueError("unexpected")) is ProviderErrorCategory.PERMANENT


def test_client_error_dispatches_through_classify_provider_exception() -> None:
    exc = _client_error("ThrottlingException")
    assert classify_provider_exception(exc) is ProviderErrorCategory.THROTTLED


def test_safe_message_for_every_category_is_non_empty_and_generic() -> None:
    for category in ProviderErrorCategory:
        message = safe_message_for(category)
        assert message
        assert "prompt" not in message.lower()
