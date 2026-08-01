"""Classifies `openai` SDK exceptions into `domain.enums.ProviderErrorCategory`.

An unmapped or unrecognized error defaults to `PERMANENT` — the safe choice, mirroring
`adapters.bedrock.error_mapping`'s policy: retrying an error we can't positively
identify as transient risks retry amplification for what might be a
non-idempotent-safe or persistently-failing request.
"""

import openai

from domain.enums import ProviderErrorCategory

# openai.APITimeoutError is a subclass of APIConnectionError (a timeout is a specific
# kind of connection failure), so it must be checked first below.
_TRANSIENT_STATUS_CODE_FLOOR = 500


def classify_provider_exception(exc: Exception) -> ProviderErrorCategory:
    """Classify any exception `OpenAIModelProvider` might catch from the `openai` SDK."""
    if isinstance(exc, openai.RateLimitError):
        return ProviderErrorCategory.THROTTLED
    if isinstance(exc, openai.APITimeoutError):
        return ProviderErrorCategory.TIMEOUT
    if isinstance(exc, openai.APIConnectionError):
        # Covers non-timeout connectivity failures (DNS, TCP reset, etc.) — a network
        # blip, not a request defect, so retryable.
        return ProviderErrorCategory.TRANSIENT
    if isinstance(exc, openai.APIStatusError):
        # RateLimitError (429) is already handled above via its own branch; every other
        # HTTP-status-carrying error is classified by status code: 5xx is the provider's
        # own fault (transient), 4xx reflects this specific request (permanent).
        if exc.status_code >= _TRANSIENT_STATUS_CODE_FLOOR:
            return ProviderErrorCategory.TRANSIENT
        return ProviderErrorCategory.PERMANENT
    return ProviderErrorCategory.PERMANENT
