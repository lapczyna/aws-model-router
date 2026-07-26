import uuid


class Uuid4IdentifierGenerator:
    """`domain.ports.IdentifierGenerator` implementation backed by `uuid4`."""

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"
