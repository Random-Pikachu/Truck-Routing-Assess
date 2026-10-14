import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def emptyCache() -> None:
    """Every test starts with an empty cache, so cached API results never leak between tests."""
    cache.clear()


@pytest.fixture(autouse=True)
def noTomTomKey(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call the real TomTom API, the ones that need a key set a fake one."""
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
