"""Provider-neutral model catalogue resolution helpers, shared by every
`domain.ports.ModelProvider` adapter (extracted from `BedrockModelProvider` in Phase 10a
when a second provider needed the identical logic — catalogue lookup, router-alias
indirection, and capability checking have nothing to do with any one provider's wire
format).
"""

from domain.catalogue import ModelDefinition
from domain.enums import ModelResolutionType, ProviderErrorCategory
from domain.errors import ProviderError
from domain.ports import ModelCatalogue
from domain.provider import ProviderRequest


def resolve_model(model_alias: str, model_catalogue: ModelCatalogue) -> ModelDefinition:
    """Look up `model_alias` in the catalogue, or raise a `PERMANENT` `ProviderError`.

    A client never supplies a raw provider model ID (ADR-006); an unknown alias here
    means the routing layer selected something the catalogue doesn't actually contain —
    a configuration defect, not a transient/retryable failure.
    """
    model = model_catalogue.get_by_alias(model_alias)
    if model is None:
        raise ProviderError(
            f"Unknown model alias: {model_alias!r}", category=ProviderErrorCategory.PERMANENT
        )
    return model


def resolve_target_model_id(model: ModelDefinition, model_catalogue: ModelCatalogue) -> str:
    """Resolve `model` to the concrete identifier its provider's API expects.

    A `router_alias` is a single, bounded indirection to another catalogue entry — not
    an arbitrary chain — so a router alias pointing at another router alias is treated as
    a configuration error rather than followed recursively.
    `adapters.config.local_model_catalogue.LocalFileModelCatalogue` already rejects a
    `router_alias` whose target belongs to a different provider at load time, so by the
    time a request reaches here, `target` (if present) is guaranteed to share `model`'s
    provider.
    """
    if model.resolution.type is not ModelResolutionType.ROUTER_ALIAS:
        return model.resolution.value

    target = model_catalogue.get_by_alias(model.resolution.value)
    if target is None or target.resolution.type is ModelResolutionType.ROUTER_ALIAS:
        raise ProviderError(
            f"Router alias {model.model_alias!r} does not resolve to an invocable model.",
            category=ProviderErrorCategory.PERMANENT,
        )
    return target.resolution.value


def check_capabilities(request: ProviderRequest, model: ModelDefinition) -> None:
    """Raise a `PERMANENT` `ProviderError` if `request` needs a capability `model`
    doesn't declare support for (`domain.catalogue.ModelCapabilities`)."""
    if request.requires_tool_use and not model.capabilities.supports_tool_use:
        raise ProviderError(
            f"Model alias {model.model_alias!r} does not support tool use.",
            category=ProviderErrorCategory.PERMANENT,
        )
    if request.requires_structured_output and not model.capabilities.supports_structured_output:
        raise ProviderError(
            f"Model alias {model.model_alias!r} does not support structured output.",
            category=ProviderErrorCategory.PERMANENT,
        )
