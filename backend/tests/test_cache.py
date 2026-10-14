import warnings
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.core.cache.backends.base import CacheKeyWarning

from routing import ors
from routing.ors import OrsError
from weather import openmeteo
from weather.openmeteo import ONE_HOUR, TIME_FORMAT, fetchHourly

START = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

GEOCODE_BODY = {
    "features": [
        {
            "geometry": {"coordinates": [-87.66063, 41.87897]},
            "properties": {"label": "Chicago, IL, USA"},
        }
    ]
}


class CountingGet:
    def __init__(self, body: dict, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.calls: list[dict] = []

    def __call__(self, url: str, params: dict, timeout: float) -> httpx.Response:
        self.calls.append(params)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def orsKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")


# --- ORS geocoding --------------------------------------------------------------


def testGeocodeIsCached(monkeypatch: pytest.MonkeyPatch, orsKey: None) -> None:
    get = CountingGet(GEOCODE_BODY)
    monkeypatch.setattr(ors.httpx, "get", get)
    first = ors.geocode("Chicago, IL")
    second = ors.geocode("  chicago, il ")  # same place, different spacing and case
    assert first == second == ((41.87897, -87.66063), "Chicago, IL, USA")
    assert len(get.calls) == 1


def testGeocodeNoMatchIsNotCached(monkeypatch: pytest.MonkeyPatch, orsKey: None) -> None:
    get = CountingGet({"features": []})
    monkeypatch.setattr(ors.httpx, "get", get)
    for _ in range(2):
        with pytest.raises(ValueError):
            ors.geocode("Nowhere")
    assert len(get.calls) == 2


def testGeocodeErrorIsNotCached(monkeypatch: pytest.MonkeyPatch, orsKey: None) -> None:
    failing = CountingGet({"error": {"code": 503, "message": "busy"}}, status=503)
    monkeypatch.setattr(ors.httpx, "get", failing)
    with pytest.raises(OrsError):
        ors.geocode("Chicago, IL")
    working = CountingGet(GEOCODE_BODY)
    monkeypatch.setattr(ors.httpx, "get", working)
    assert ors.geocode("Chicago, IL")[1] == "Chicago, IL, USA"
    assert len(working.calls) == 1


def testAutocompleteIsCachedPerSize(monkeypatch: pytest.MonkeyPatch, orsKey: None) -> None:
    get = CountingGet(GEOCODE_BODY)
    monkeypatch.setattr(ors.httpx, "get", get)
    ors.autocomplete("Chica")
    ors.autocomplete("chica")
    assert len(get.calls) == 1
    ors.autocomplete("Chica", size=3)
    assert len(get.calls) == 2


def testPlaceNamesMakeSafeCacheKeys(monkeypatch: pytest.MonkeyPatch, orsKey: None) -> None:
    monkeypatch.setattr(ors.httpx, "get", CountingGet(GEOCODE_BODY))
    with warnings.catch_warnings():
        warnings.simplefilter("error", CacheKeyWarning)
        ors.geocode("New York, NY  (Manhattan) — 5th Ave")
    assert " " not in ors.textCacheKey("ors:geocode", "New York, NY")


# --- ORS routes -----------------------------------------------------------------


class CountingDirections:
    def __init__(self, failFirst: bool = False) -> None:
        self.calls = 0
        self.failFirst = failFirst

    def __call__(self, coordinates: list, alternatives: bool) -> list[dict]:
        self.calls += 1
        if self.failFirst and self.calls == 1:
            raise OrsError(503, "busy")
        lonLat = []
        spread = 0.0  # differs per via-point, so the detours are not duplicates of each other
        for lat, lon in coordinates:
            lonLat.append([lon, lat])
            spread += abs(lat) + abs(lon)
        seconds = 30.0 * spread
        step = {"way_points": [0, len(lonLat) - 1], "duration": seconds}
        feature = {
            "geometry": {"coordinates": lonLat},
            "properties": {
                "segments": [{"steps": [step]}],
                "summary": {"distance": 1000.0 * spread, "duration": seconds},
            },
        }
        return [feature]


CHICAGO = (41.8781, -87.6298)
ST_LOUIS = (38.627, -90.1994)
DENVER = (39.7392, -104.9903)


def testRoutesAreCached(monkeypatch: pytest.MonkeyPatch) -> None:
    directions = CountingDirections()
    monkeypatch.setattr(ors, "requestDirections", directions)
    first = ors.getRouteOptions(CHICAGO, ST_LOUIS)
    callsAfterFirst = directions.calls
    second = ors.getRouteOptions(CHICAGO, ST_LOUIS)
    assert callsAfterFirst == 3  # direct + two via routes
    assert directions.calls == callsAfterFirst
    assert [r.routeId for r in second] == [r.routeId for r in first]


def testRoutesForADifferentTripAreFetched(monkeypatch: pytest.MonkeyPatch) -> None:
    directions = CountingDirections()
    monkeypatch.setattr(ors, "requestDirections", directions)
    ors.getRouteOptions(CHICAGO, ST_LOUIS)
    ors.getRouteOptions(CHICAGO, DENVER)
    ors.getRouteOptions(ST_LOUIS, CHICAGO)  # the reverse trip is its own entry
    assert directions.calls == 9


def testRouteErrorsAreNotCached(monkeypatch: pytest.MonkeyPatch) -> None:
    directions = CountingDirections(failFirst=True)
    monkeypatch.setattr(ors, "requestDirections", directions)
    with pytest.raises(OrsError):
        ors.getRouteOptions(CHICAGO, ST_LOUIS)
    assert len(ors.getRouteOptions(CHICAGO, ST_LOUIS)) == 3


# --- weather --------------------------------------------------------------------


class FakeForecast:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, url: str, params: dict, timeout: float) -> httpx.Response:
        self.calls.append(params)
        lats = params["latitude"].split(",")
        lons = params["longitude"].split(",")
        start = datetime.strptime(params["start_hour"], TIME_FORMAT)
        end = datetime.strptime(params["end_hour"], TIME_FORMAT)
        hours = int((end - start) / ONE_HOUR) + 1
        times = []
        for i in range(hours):
            times.append((start + i * ONE_HOUR).strftime(TIME_FORMAT))
        locations = []
        for i in range(len(lats)):
            hourly = {
                "time": times,
                "wind_speed_10m": [float(lats[i])] * hours,
                "wind_gusts_10m": [None] * hours,
                "rain": [0.1] * hours,
                "showers": [0.0] * hours,
                "snowfall": [0.0] * hours,
            }
            locations.append(
                {"latitude": float(lats[i]), "longitude": float(lons[i]), "hourly": hourly}
            )
        return httpx.Response(200, json=locations if len(locations) > 1 else locations[0])

    def locations(self) -> int:
        total = 0
        for params in self.calls:
            total += len(params["latitude"].split(","))
        return total


@pytest.fixture
def forecast(monkeypatch: pytest.MonkeyPatch) -> FakeForecast:
    fake = FakeForecast()
    monkeypatch.setattr(openmeteo.httpx, "get", fake)
    return fake


POINTS = [(41.88, -87.63), (40.0, -89.0), (38.63, -90.2)]


def testSameWindowIsServedFromCache(forecast: FakeForecast) -> None:
    first = fetchHourly(POINTS, START, START + 5 * ONE_HOUR)
    second = fetchHourly(POINTS, START, START + 5 * ONE_HOUR)
    assert len(forecast.calls) == 1
    for key in first:
        assert second[key].wind == first[key].wind
        assert second[key].times == first[key].times
        assert second[key].gust == [None] * 6  # missing values survive the cache as None


def testNarrowerWindowIsServedFromCache(forecast: FakeForecast) -> None:
    fetchHourly(POINTS, START, START + 48 * ONE_HOUR)
    result = fetchHourly(POINTS, START + 10 * ONE_HOUR, START + 12 * ONE_HOUR)
    assert len(forecast.calls) == 1
    for series in result.values():
        assert series.times[0] == START + 10 * ONE_HOUR
        assert len(series.times) == 3


def testWiderWindowFetchesAgain(forecast: FakeForecast) -> None:
    fetchHourly(POINTS, START, START + 5 * ONE_HOUR)
    fetchHourly(POINTS, START, START + 10 * ONE_HOUR)
    assert len(forecast.calls) == 2


def testOnlyUncachedCellsAreFetched(forecast: FakeForecast) -> None:
    fetchHourly(POINTS[:2], START, START + 5 * ONE_HOUR)
    result = fetchHourly(POINTS, START, START + 5 * ONE_HOUR)
    assert forecast.locations() == 3  # 2 the first time, only the new one the second time
    assert len(result) == 3


def testCachedWeatherExpires(forecast: FakeForecast, monkeypatch: pytest.MonkeyPatch) -> None:
    assert openmeteo.WEATHER_CACHE_SECONDS <= 60 * 60
    fetchHourly(POINTS, START, START + 2 * ONE_HOUR)
    later = datetime.now() + timedelta(seconds=openmeteo.WEATHER_CACHE_SECONDS + 1)
    monkeypatch.setattr("django.core.cache.backends.locmem.time.time", lambda: later.timestamp())
    fetchHourly(POINTS, START, START + 2 * ONE_HOUR)
    assert len(forecast.calls) == 2
