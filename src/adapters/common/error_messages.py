"""Fixed, safe error messages per `domain.enums.ProviderErrorCategory`, shared by every
provider adapter — never derived from a provider's own exception text, which could echo
request details back to a caller.
"""

from domain.enums import ProviderErrorCategory

_SAFE_MESSAGES: dict[ProviderErrorCategory, str] = {
    ProviderErrorCategory.THROTTLED: "The model provider throttled this request.",
    ProviderErrorCategory.TRANSIENT: "The model provider returned a transient error.",
    ProviderErrorCategory.TIMEOUT: "The model provider timed out.",
    ProviderErrorCategory.PERMANENT: "The model provider rejected this request.",
}


def safe_message_for(category: ProviderErrorCategory) -> str:
    return _SAFE_MESSAGES[category]
