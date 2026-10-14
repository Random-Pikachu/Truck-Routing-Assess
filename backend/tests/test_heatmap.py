import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from risk.engine import RiskLevel
from routing import ors
from routing.checkpoints import Point, Step, haversine
from routing.ors import RouteOption
from trips.heatmap import (
    CORRIDOR_HALF_WIDTH_MILES,
    HEATMAP_GRID_DEGREES,
    HEATMAP_HOURS,
    MAX_SAMPLES_PER_ROUTE,
    MILES_PER_DEGREE,
    buildHeatmap,
    corridorPoints,
    heatmapGridKey,
    offsetPoint,
    riskAt,
)
from weather import openmeteo
from weather.openmeteo import ONE_HOUR, HourlySeries, gridKey

NOW = datetime(2026, 10, 14, 9, 40, tzinfo=UTC)
START = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
ORS_FIXTURES = Path(__file__).parent / "fixtures" / "ors"


def northRoute(lon: float, miles: float, startLat: float = 38.0) -> list[Point]:
    return [(startLat, lon), (startLat + miles / MILES_PER_DEGREE, lon)]


def fixtureRoute(name: str) -> list[Point]:
    feature = json.loads((ORS_FIXTURES / name).read_text())["features"][0]
    return ors.parseRoute(feature, "A").points


# --- geometry -------------------------------------------------------------------


def testHeatmapGridKey() -> None:
    assert heatmapGridKey((41.8781, -87.6298)) == (42.0, -87.75)
    assert heatmapGridKey((38.60, -90.10)) == (38.5, -90.0)


@pytest.mark.parametrize(
    ("behind", "ahead", "westOrEast", "northOrSouth"),
    [
        pytest.param((39.9, -89.0), (40.1, -89.0), -1, 0, id="heading north: left is west"),
        pytest.param((40.0, -89.1), (40.0, -88.9), 0, 1, id="heading east: left is north"),
    ],
)
def testOffsetPointGoesLeftOfTheDirectionOfTravel(
    behind: Point, ahead: Point, westOrEast: int, northOrSouth: int
) -> None:
    center = (40.0, -89.0)
    left = offsetPoint(center, behind, ahead, 20)
    right = offsetPoint(center, behind, ahead, -20)
    assert haversine(center, left) == pytest.approx(20, abs=0.05)
    assert haversine(center, right) == pytest.approx(20, abs=0.05)
    if westOrEast:
        assert (left[1] - center[1]) * westOrEast > 0
        assert (right[1] - center[1]) * westOrEast < 0
    if northOrSouth:
        assert (left[0] - center[0]) * northOrSouth > 0


def testOffsetPointWithoutDirectionOrDistanceStaysPut() -> None:
    center = (40.0, -89.0)
    assert offsetPoint(center, center, center, 20) == center
    assert offsetPoint(center, (39.9, -89.0), (40.1, -89.0), 0) == center


def testCorridorCoversBothSidesOfTheRoute() -> None:
    points = corridorPoints([northRoute(-90.0, 200)])
    lons = [lon for _, lon in points]
    assert min(lons) < -90.0 < max(lons)
    widest = max(abs(lon + 90.0) for lon in lons) * MILES_PER_DEGREE * 0.78  # cos(~39 deg)
    assert widest == pytest.approx(
        CORRIDOR_HALF_WIDTH_MILES, abs=HEATMAP_GRID_DEGREES * MILES_PER_DEGREE
    )


def testCorridorPointsSitOnTheHeatmapGrid() -> None:
    for lat, lon in corridorPoints([northRoute(-90.0, 200)]):
        assert (lat / HEATMAP_GRID_DEGREES) == pytest.approx(round(lat / HEATMAP_GRID_DEGREES))
        assert (lon / HEATMAP_GRID_DEGREES) == pytest.approx(round(lon / HEATMAP_GRID_DEGREES))


def testCorridorSharesPointsBetweenRoutes() -> None:
    route = fixtureRoute("directions_long_direct.json")
    once = corridorPoints([route])
    assert corridorPoints([route, route, route]) == once
    both = corridorPoints([route, fixtureRoute("directions_long_via.json")])
    assert len(once) < len(both) < 2 * len(once)


def testCorridorSizeForARealRoute() -> None:
    assert 25 <= len(corridorPoints([fixtureRoute("directions_long_direct.json")])) <= 60


def testLongRoutesAreSampledMoreSparsely() -> None:
    points = corridorPoints([northRoute(-100.0, 1500, startLat=30.0)])
    assert len(points) <= 3 * (MAX_SAMPLES_PER_ROUTE + 1)
    lats = sorted({lat for lat, _ in points})
    assert lats[-1] - lats[0] == pytest.approx(1500 / MILES_PER_DEGREE, abs=0.5)  # still end to end


def testSinglePointRoute() -> None:
    assert corridorPoints([[(40.01, -89.02)]]) == [(40.0, -89.0)]


# --- risk per frame -------------------------------------------------------------


def series(wind: list, rain: list, snow: list | None = None) -> HourlySeries:
    times = []
    for i in range(len(wind)):
        times.append(START + i * ONE_HOUR)
    return HourlySeries(times, wind, [None] * len(wind), rain, snow or [0.0] * len(wind))


def testRiskAtUsesWindAtTheHourAndRainOverTheHour() -> None:
    hourly = series(wind=[10, 40, 10], rain=[0.0, 0.0, 0.3])
    assert riskAt(hourly, START, 20_000) == RiskLevel.LOW  # wind 10, rain 9-10 = 0
    assert riskAt(hourly, START + ONE_HOUR, 20_000) == RiskLevel.HIGH  # wind 40, rain 10-11 = 0.3


def testRiskAtUsesTheLoad() -> None:
    hourly = series(wind=[40, 40], rain=[0.0, 0.0])
    assert riskAt(hourly, START, 20_000) == RiskLevel.HIGH
    assert riskAt(hourly, START, 45_000) == RiskLevel.SEVERE


def testRiskAtMissingDataIsNone() -> None:
    assert riskAt(None, START, 20_000) is None
    assert riskAt(series(wind=[None, 10], rain=[0.0, 0.0]), START, 20_000) is None
    assert riskAt(series(wind=[10, 10], rain=[0.0, None]), START, 20_000) is None
    assert riskAt(series(wind=[10], rain=[0.0]), START, 20_000) is None  # no hour after it


# --- buildHeatmap ---------------------------------------------------------------


class FakeServices:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.places = {"Chicago": (41.8781, -87.6298), "St. Louis": (38.627, -90.1994)}
        self.routes = [
            RouteOption("A", northRoute(-90.0, 100), [Step(0, 1, 7200)], 100, 7200),
            RouteOption("B", northRoute(-88.0, 120), [Step(0, 1, 9000)], 120, 9000),
        ]
        self.geocodeCalls: list[str] = []
        self.windows: list[tuple[datetime, datetime]] = []
        self.missing: set[Point] = set()
        monkeypatch.setattr(ors, "geocode", self.geocode)
        monkeypatch.setattr(ors, "getRouteOptions", lambda origin, destination: self.routes)
        monkeypatch.setattr(openmeteo, "fetchHourly", self.fetchHourly)

    def geocode(self, text: str) -> tuple[Point, str]:
        self.geocodeCalls.append(text)
        return self.places[text], text

    def fetchHourly(self, points: list[Point], startHour: datetime, endHour: datetime) -> dict:
        self.windows.append((startHour, endHour))
        hours = int((endHour - startHour) / ONE_HOUR) + 1
        result = {}
        for point in points:
            key = gridKey(point)
            if key in self.missing:
                continue
            wind = []
            for h in range(hours):
                wind.append(2.0 * h)  # calm now, 25 mph by hour 13, 55 mph by hour 28
            times = []
            for h in range(hours):
                times.append(startHour + h * ONE_HOUR)
            result[key] = HourlySeries(times, wind, [None] * hours, [0.0] * hours, [0.0] * hours)
        return result


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> FakeServices:
    return FakeServices(monkeypatch)


def testHeatmapHasOneFramePerHour(services: FakeServices) -> None:
    result = buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW)
    assert result.startHour == START
    assert len(result.risk) == HEATMAP_HOURS + 1
    for row in result.risk:
        assert len(row) == len(result.points)


def testHeatmapRequestsTheWholeWindowOnce(services: FakeServices) -> None:
    buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW)
    assert services.windows == [(START, START + (HEATMAP_HOURS + 1) * ONE_HOUR)]


def testHeatmapRiskChangesOverTime(services: FakeServices) -> None:
    risk = buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW).risk
    assert set(risk[0]) == {RiskLevel.LOW}
    assert set(risk[13]) == {RiskLevel.MODERATE}  # 26 mph
    assert set(risk[28]) == {RiskLevel.NO_TRAVEL}  # 56 mph


def testHeatmapUsesTheLoad(services: FakeServices) -> None:
    light = buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW).risk
    heavy = buildHeatmap("Chicago", "St. Louis", 45_000, now=NOW).risk
    assert set(light[20]) == {RiskLevel.HIGH}  # 40 mph
    assert set(heavy[20]) == {RiskLevel.SEVERE}


def testHeatmapMissingWeatherIsNoneNotLow(services: FakeServices) -> None:
    firstPoint = corridorPoints([services.routes[0].points])[0]
    services.missing.add(gridKey(firstPoint))
    result = buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW)
    column = result.points.index(firstPoint)
    for row in result.risk:
        assert row[column] is None


def testHeatmapCoversEveryRoute(services: FakeServices) -> None:
    lons = [lon for _, lon in buildHeatmap("Chicago", "St. Louis", 20_000, now=NOW).points]
    assert min(lons) < -90.0 and max(lons) > -88.0


@pytest.mark.parametrize(
    ("origin", "destination", "load", "message"),
    [
        pytest.param("Chicago", "St. Louis", -5, "negative", id="negative load"),
        pytest.param("Chicago", "Chicago", 20_000, "same place", id="same place"),
    ],
)
def testHeatmapRejectsBadRequests(
    services: FakeServices, origin: str, destination: str, load: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        buildHeatmap(origin, destination, load, now=NOW)
    if load < 0:
        assert services.geocodeCalls == []
