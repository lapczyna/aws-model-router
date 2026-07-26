from datetime import UTC, datetime


class SystemClock:
    """`domain.ports.Clock` implementation backed by the real system time (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)
