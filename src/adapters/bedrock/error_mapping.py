"""Classifies boto3/botocore exceptions into `domain.enums.ProviderErrorCategory`.

An unmapped or unrecognized error defaults to `PERMANENT` — the safe choice, since
retrying an error we can't positively identify as transient risks retry amplification
for what might be a non-idempotent-safe or persistently-failing request ("Do not retry
blindly", `docs/requirements.md`).
"""

from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from adapters.common.error_messages import safe_message_for
from domain.enums import ProviderErrorCategory

__all__ = ["classify_client_error", "classify_provider_exception", "safe_message_for"]

_THROTTLED_CODES = frozenset({"ThrottlingException", "TooManyRequestsException"})
_TIMEOUT_CODES = frozenset({"ModelTimeoutException"})
_TRANSIENT_CODES = frozenset(
    {"ServiceUnavailableException", "InternalServerException", "ModelNotReadyException"}
)


def classify_client_error(exc: ClientError) -> ProviderErrorCategory:
    code = exc.response.get("Error", {}).get("Code", "")
    if code in _THROTTLED_CODES:
        return ProviderErrorCategory.THROTTLED
    if code in _TIMEOUT_CODES:
        return ProviderErrorCategory.TIMEOUT
    if code in _TRANSIENT_CODES:
        return ProviderErrorCategory.TRANSIENT
    return ProviderErrorCategory.PERMANENT


def classify_provider_exception(exc: Exception) -> ProviderErrorCategory:
    """Classify any exception `BedrockModelProvider` might catch from boto3/botocore."""
    if isinstance(exc, ClientError):
        return classify_client_error(exc)
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
        return ProviderErrorCategory.TIMEOUT
    if isinstance(exc, BotoCoreError):
        # Covers EndpointConnectionError and other network-level botocore failures not
        # specifically classified above — treated as transient (retryable) rather than
        # permanent, since these are typically connectivity blips, not request defects.
        return ProviderErrorCategory.TRANSIENT
    return ProviderErrorCategory.PERMANENT
