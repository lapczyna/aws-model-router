"""Monetary value handling.

Money is always `Decimal`, never `float` (binary floating point introduces rounding
error that is unacceptable for cost accounting). `Money` rejects raw `float` input at
the pydantic validation boundary — config authors must quote monetary values as strings
in YAML/JSON (e.g. `"0.00025"`), which pydantic then parses exactly into `Decimal`.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        # pydantic only converts ValueError/AssertionError raised by a validator into
        # a ValidationError — a TypeError here would instead propagate as an opaque,
        # unwrapped exception.
        raise ValueError(
            "monetary values must be given as a string or Decimal, not float "
            '(binary floats introduce rounding error) — quote the value, e.g. "0.00025"'
        )
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]
