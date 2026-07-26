import pytest

from shared.clock import SystemClock
from shared.identifiers import Uuid4IdentifierGenerator

pytestmark = pytest.mark.unit


def test_system_clock_returns_timezone_aware_utc() -> None:
    now = SystemClock().now()
    offset = now.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_identifier_generator_prefixes_and_is_unique() -> None:
    generator = Uuid4IdentifierGenerator()

    first = generator.new_id("dec")
    second = generator.new_id("dec")

    assert first.startswith("dec_")
    assert second.startswith("dec_")
    assert first != second
