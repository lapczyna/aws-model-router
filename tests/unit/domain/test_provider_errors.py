import pytest

from domain.enums import ProviderErrorCategory
from domain.errors import DomainError, ProviderError

pytestmark = pytest.mark.unit


def test_provider_error_carries_category() -> None:
    error = ProviderError("something went wrong", category=ProviderErrorCategory.THROTTLED)

    assert error.category is ProviderErrorCategory.THROTTLED
    assert str(error) == "something went wrong"


def test_provider_error_is_a_domain_error() -> None:
    assert issubclass(ProviderError, DomainError)


@pytest.mark.parametrize("category", list(ProviderErrorCategory))
def test_provider_error_accepts_every_category(category: ProviderErrorCategory) -> None:
    error = ProviderError("message", category=category)
    assert error.category is category
