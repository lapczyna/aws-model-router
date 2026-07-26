from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from domain.money import Money

pytestmark = pytest.mark.unit


class _Wrapper(BaseModel):
    model_config = ConfigDict(frozen=True)
    amount: Money


def test_money_accepts_quoted_decimal_string() -> None:
    wrapper = _Wrapper.model_validate({"amount": "0.00025"})
    assert wrapper.amount == Decimal("0.00025")


def test_money_accepts_decimal_instance() -> None:
    wrapper = _Wrapper.model_validate({"amount": Decimal("1.5")})
    assert wrapper.amount == Decimal("1.5")


def test_money_rejects_raw_float() -> None:
    with pytest.raises(ValidationError):
        _Wrapper.model_validate({"amount": 0.00025})
