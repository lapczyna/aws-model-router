"""Provider-independent invocation models (ADR-002, ADR-009).

`ProviderRequest`/`ProviderResponse` are the shape every `ModelProvider` implementation
speaks — never a provider's native wire format. `BedrockModelProvider` (Phase 3) maps
these to and from the Bedrock Converse API; a second provider would map them to its own
native request/response shape without changing anything above the `ModelProvider`
boundary.
"""

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import ProviderName, StopReason
from domain.messages import Message
from domain.usage import Usage


class ProviderRequest(BaseModel):
    """A capability-checked, policy-resolved request ready to invoke a specific model.

    Unlike `domain.requirements.RoutingRequirements`, this is not client input — it is
    built by the routing/invocation orchestrator *after* a `RoutingDecision` has already
    selected `model_alias`, so every field here is trusted, resolved, and bounded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    messages: tuple[Message, ...] = Field(min_length=1)
    system_prompt: str | None = None
    max_output_tokens: int = Field(gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_tool_use: bool = False
    requires_structured_output: bool = False


class ProviderResponse(BaseModel):
    """A provider's response, normalized into a stable, provider-independent shape."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    provider: ProviderName
    message: Message
    stop_reason: StopReason
    usage: Usage
