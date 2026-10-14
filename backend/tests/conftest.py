import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def emptyCache() -> None:
    """Every test starts with an empty cache, so cached API results never leak between tests."""
    cache.clear()
