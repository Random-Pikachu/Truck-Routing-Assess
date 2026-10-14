import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from risk.engine import RiskLevel, classify
from routing.checkpoints import Checkpoint
from weather import openmeteo
from weather.openmeteo import (
    ONE_HOUR,
    TIME_FORMAT,
    HourlySeries,
    WeatherError,
    ceilHour,
    fetchHourly,
    floorHour,
    gridKey,
    nearestHour,
    parseSeries,
    pickReading,
    requestChunk,
    weatherForCheckpoints,
)

FIXTURES = Path(__file__).parent / "fixtures" / "openmeteo"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)


def loadFixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 14, hour, minute, tzinfo=UTC)


def checkpoint(lat: float, lon: float, eta: datetime, mile: float = 0.0) -> Checkpoint:
    return Checkpoint(mile=mile, lat=lat, lon=lon, secondsFromStart=0.0, eta=eta)


class FakeOpenMeteo:
    """Stands in for httpx.get: answers any request, wind = the location's latitude."""

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
            lat = float(lats[i])
            hourly = {
                "time": times,
                "wind_speed_10m": [lat] * hours,
                "wind_gusts_10m": [lat + 5] * hours,
                "rain": [0.1] * hours,
                "showers": [0.05] * hours,
                "snowfall": [0.0] * hours,
            }
            locations.append({"latitude": lat, "longitude": float(lons[i]), "hourly": hourly})

        return httpx.Response(200, json=locations if len(locations) > 1 else locations[0])

    def requestedLocations(self) -> int:
        total = 0
        for params in self.calls:
            total += len(params["latitude"].split(","))
        return total


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOpenMeteo:
    server = FakeOpenMeteo()
    monkeypatch.setattr(openmeteo.httpx, "get", server)
    return server


def replyWith(monkeypatch: pytest.MonkeyPatch, *responses: object) -> list[dict]:
    """httpx.get returns these in order (an exception instance is raised instead)."""
    calls: list[dict] = []
    queue = list(responses)

    def get(url: str, params: dict, timeout: float) -> httpx.Response:
        calls.append(params)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, httpx.Response)
        return reply

    monkeypatch.setattr(openmeteo.httpx, "get", get)
    return calls


# --- hours --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "floor", "ceil", "nearest"),
    [
        pytest.param(at(14, 29), at(14), at(15), at(14), id="14:29"),
        pytest.param(at(14, 30), at(14), at(15), at(15), id="14:30 rounds up"),
        pytest.param(at(14), at(14), at(14), at(14), id="exactly on the hour"),
        pytest.param(at(14, 1), at(14), at(15), at(14), id="14:01"),
    ],
)
def testHourHelpers(moment: datetime, floor: datetime, ceil: datetime, nearest: datetime) -> None:
    assert floorHour(moment) == floor
    assert ceilHour(moment) == ceil
    assert nearestHour(moment) == nearest


def testHourHelpersConvertToUtc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    moment = datetime(2026, 10, 14, 19, 59, tzinfo=ist)  # 14:29 UTC
    assert floorHour(moment) == at(14)
    assert ceilHour(moment) == at(15)
    assert nearestHour(moment) == at(14)


# --- gridKey ------------------------------------------------------------------


def testGridKeyRoundsToTenthOfADegree() -> None:
    assert gridKey((41.8781, -87.6298)) == (41.9, -87.6)
    assert gridKey((38.6270, -90.1994)) == (38.6, -90.2)


def testGridKeyMergesNearbyPoints() -> None:
    assert gridKey((41.8781, -87.6298)) == gridKey((41.8912, -87.6401))
    assert gridKey((41.8781, -87.6298)) != gridKey((41.6781, -87.6298))


# --- parseSeries (real response) ----------------------------------------------


def testFixtureWasRequestedInTheRiskTableUnits() -> None:
    units = loadFixture("forecast_3_locations.json")[0]["hourly_units"]
    assert units["wind_speed_10m"] == "mp/h"
    assert units["rain"] == units["showers"] == units["snowfall"] == "inch"


def testParseSeriesRealResponse() -> None:
    series = parseSeries(loadFixture("forecast_3_locations.json")[2])
    assert series.times[0] == WINDOW_START
    assert series.times[-1] == WINDOW_END
    assert len(series.times) == len(series.wind) == len(series.rain) == len(series.snow) == 7
    assert series.times[0].tzinfo is UTC
    assert series.rain[2] == pytest.approx(0.185)


def testParseSeriesAddsShowersToRain() -> None:
    location = {
        "hourly": {
            "time": ["2026-10-14T12:00", "2026-10-14T13:00"],
            "wind_speed_10m": [5.0, 6.0],
            "wind_gusts_10m": [9.0, 10.0],
            "rain": [0.1, None],
            "showers": [0.05, 0.2],
            "snowfall": [0.0, 0.0],
        }
    }
    series = parseSeries(location)
    assert series.rain[0] == pytest.approx(0.15)
    assert series.rain[1] is None


# --- pickReading --------------------------------------------------------------


@pytest.fixture
def stLouis() -> HourlySeries:
    # hourly wind 7.7 5.8 6.7 6.9 3.0 1.3 2.3, rain 0 0 0.185 0 0 0 0.055 (12:00 .. 18:00)
    return parseSeries(loadFixture("forecast_3_locations.json")[2])


def testPickReadingWindNearestRainFromTheHourBeingDriven(stLouis: HourlySeries) -> None:
    """ETA 13:20: wind at 13:00, rain for 13:00-14:00 (labelled 14:00)."""
    reading = pickReading(stLouis, at(13, 20))
    assert reading is not None
    assert reading.windMph == pytest.approx(5.8)
    assert reading.rainInHr == pytest.approx(0.185)
    assert reading.forecastHour == at(13)


def testPickReadingAfterTheRainyHour(stLouis: HourlySeries) -> None:
    """ETA 14:10: rain now comes from 14:00-15:00, which was dry."""
    reading = pickReading(stLouis, at(14, 10))
    assert reading is not None
    assert reading.windMph == pytest.approx(6.7)
    assert reading.rainInHr == pytest.approx(0.0)


def testPickReadingExactlyOnTheHour(stLouis: HourlySeries) -> None:
    reading = pickReading(stLouis, at(14))
    assert reading is not None
    assert reading.windMph == pytest.approx(6.7)
    assert reading.rainInHr == pytest.approx(0.185)


@pytest.mark.parametrize("eta", [at(11, 10), at(18, 10), at(20)])
def testPickReadingOutsideTheWindowIsUnavailable(stLouis: HourlySeries, eta: datetime) -> None:
    assert pickReading(stLouis, eta) is None


def testPickReadingAtTheLastHourOfTheWindow(stLouis: HourlySeries) -> None:
    """ETA 17:40 still fits: wind at 18:00, rain for 17:00-18:00."""
    reading = pickReading(stLouis, at(17, 40))
    assert reading is not None
    assert reading.rainInHr == pytest.approx(0.055)


def testPickReadingMissingValueIsUnavailableNotZero() -> None:
    series = HourlySeries(
        times=[at(12), at(13)],
        wind=[None, 5.0],
        gust=[None, None],
        rain=[0.0, 0.0],
        snow=[0.0, 0.0],
    )
    assert pickReading(series, at(12)) is None
    reading = pickReading(series, at(13))
    assert reading is not None
    assert reading.gustMph is None  # a missing gust alone is fine, it is display only


def testRealReadingFeedsTheRiskEngine(stLouis: HourlySeries) -> None:
    reading = pickReading(stLouis, at(13, 20))
    assert reading is not None
    level = classify(reading.windMph, reading.rainInHr, reading.snowInHr, 20_000)
    assert level == RiskLevel.MODERATE  # 0.185 in/hr rain


# --- requestChunk -------------------------------------------------------------


def testRequestChunkSendsUnitsAndWindow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = replyWith(
        monkeypatch, httpx.Response(200, json=loadFixture("forecast_3_locations.json"))
    )
    points = [(41.9, -87.6), (40.9, -89.7), (38.6, -90.2)]
    series = requestChunk(points, WINDOW_START, WINDOW_END)

    assert len(series) == 3
    params = calls[0]
    assert params["latitude"] == "41.9000,40.9000,38.6000"
    assert params["longitude"] == "-87.6000,-89.7000,-90.2000"
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["timezone"] == "GMT"
    assert params["start_hour"] == "2026-10-14T12:00"
    assert params["end_hour"] == "2026-10-14T18:00"


def testRequestChunkSingleLocationObject(monkeypatch: pytest.MonkeyPatch) -> None:
    single = loadFixture("forecast_3_locations.json")[0]
    replyWith(monkeypatch, httpx.Response(200, json=single))
    assert len(requestChunk([(41.9, -87.6)], WINDOW_START, WINDOW_END)) == 1


def testRequestChunkWrongLocationCount(monkeypatch: pytest.MonkeyPatch) -> None:
    replyWith(monkeypatch, httpx.Response(200, json=loadFixture("forecast_3_locations.json")))
    with pytest.raises(WeatherError):
        requestChunk([(41.9, -87.6), (40.9, -89.7)], WINDOW_START, WINDOW_END)


def testRequestChunkClientErrorShowsReasonAndIsNotRetried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = replyWith(monkeypatch, httpx.Response(400, json=loadFixture("error_out_of_range.json")))
    with pytest.raises(WeatherError, match="out of allowed range"):
        requestChunk([(41.9, -87.6)], WINDOW_START, WINDOW_END)
    assert len(calls) == 1


def testRequestChunkRetriesServerErrorOnce(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = httpx.Response(200, json=loadFixture("forecast_3_locations.json")[0])
    calls = replyWith(monkeypatch, httpx.Response(503, json={"reason": "busy"}), ok)
    assert len(requestChunk([(41.9, -87.6)], WINDOW_START, WINDOW_END)) == 1
    assert len(calls) == 2


def testRequestChunkRetriesTimeoutThenGivesUp(monkeypatch: pytest.MonkeyPatch) -> None:
    timeout = httpx.ReadTimeout("slow")
    calls = replyWith(monkeypatch, timeout, httpx.ReadTimeout("still slow"))
    with pytest.raises(WeatherError, match="request failed"):
        requestChunk([(41.9, -87.6)], WINDOW_START, WINDOW_END)
    assert len(calls) == 2


# --- fetchHourly --------------------------------------------------------------


def testFetchHourlyDeduplicatesNearbyPoints(fake: FakeOpenMeteo) -> None:
    points = [(41.8781, -87.6298), (41.8912, -87.6401), (38.627, -90.1994), (38.63, -90.2)]
    result = fetchHourly(points, WINDOW_START, WINDOW_END)
    assert len(result) == 2
    assert fake.requestedLocations() == 2


def testFetchHourlyBatchesAndMapsResultsBack(fake: FakeOpenMeteo) -> None:
    points = []
    for i in range(60):
        points.append((30 + i * 0.3, -90.0))
    result = fetchHourly(points, WINDOW_START, WINDOW_END)

    assert len(fake.calls) == 3  # 25 + 25 + 10
    assert fake.requestedLocations() == 60
    for point in points:
        key = gridKey(point)
        assert result[key].wind[0] == pytest.approx(key[0])  # fake wind = latitude


def testFetchHourlyNoPointsMakesNoRequest(fake: FakeOpenMeteo) -> None:
    assert fetchHourly([], WINDOW_START, WINDOW_END) == {}
    assert fake.calls == []


# --- weatherForCheckpoints ----------------------------------------------------


def testWeatherForCheckpointsKeepsOrderAndLength(fake: FakeOpenMeteo) -> None:
    checkpoints = [
        checkpoint(41.88, -87.63, at(12, 10)),
        checkpoint(40.0, -89.0, at(14, 40)),
        checkpoint(38.63, -90.20, at(16, 5)),
    ]
    readings = weatherForCheckpoints(checkpoints, now=NOW)
    assert len(readings) == 3
    winds = []
    for reading in readings:
        assert reading is not None
        winds.append(reading.windMph)
    assert winds == pytest.approx([41.9, 40.0, 38.6])
    assert readings[0].rainInHr == pytest.approx(0.15)  # rain 0.1 + showers 0.05


def testWeatherForCheckpointsRequestsOnlyTheTripWindow(fake: FakeOpenMeteo) -> None:
    checkpoints = [checkpoint(41.88, -87.63, at(12, 10)), checkpoint(38.63, -90.20, at(16, 5))]
    weatherForCheckpoints(checkpoints, now=NOW)
    assert fake.calls[0]["start_hour"] == "2026-10-14T12:00"
    assert fake.calls[0]["end_hour"] == "2026-10-14T17:00"


def testWeatherForCheckpointsSharesOneRequestAcrossRoutes(fake: FakeOpenMeteo) -> None:
    """Three routes from the same origin: the origin is fetched once."""
    checkpoints = []
    for _ in range(3):
        checkpoints.append(checkpoint(41.8781, -87.6298, at(12)))
    checkpoints.append(checkpoint(40.0, -89.0, at(14)))
    weatherForCheckpoints(checkpoints, now=NOW)
    assert fake.requestedLocations() == 2


def testWeatherBeyondTheHorizonIsUnavailable(fake: FakeOpenMeteo) -> None:
    far = NOW + timedelta(days=20)
    readings = weatherForCheckpoints(
        [checkpoint(41.88, -87.63, at(12)), checkpoint(38.63, -90.20, far)], now=NOW
    )
    assert readings[0] is not None
    assert readings[1] is None
    assert "2026-11" not in fake.calls[0]["end_hour"]


def testWeatherAllBeyondTheHorizonMakesNoRequest(fake: FakeOpenMeteo) -> None:
    far = NOW + timedelta(days=20)
    readings = weatherForCheckpoints([checkpoint(41.88, -87.63, far)], now=NOW)
    assert readings == [None]
    assert fake.calls == []


def testWeatherForNoCheckpoints(fake: FakeOpenMeteo) -> None:
    assert weatherForCheckpoints([], now=NOW) == []
    assert fake.calls == []
