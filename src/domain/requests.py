from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.messages import Message
from domain.requirements import RoutingRequirements


class ApplicationIdentity(BaseModel):
    """The authenticated identity of a calling application.

    Minimal by design in Phase 2 — authentication/authorization is a Phase 5 concern.
    This exists now so downstream code depends on a stable type rather than a bare
    string, and can grow (e.g. authorized scopes) without changing call sites.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    application_id: str


class InferenceRequest(BaseModel):
    """The normalized, validated representation of a client's inference request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    application_id: str
    messages: tuple[Message, ...] = Field(min_length=1)
    requirements: RoutingRequirements
    conversation_id: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("application_id")
    @classmethod
    def _application_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("application_id must not be blank")
        return value
