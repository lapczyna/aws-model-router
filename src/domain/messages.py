from pydantic import BaseModel, ConfigDict

from domain.enums import Role


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    content: str
