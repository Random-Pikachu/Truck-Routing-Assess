import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from risk.engine import RiskLevel
from routing import ors
from routing.checkpoints import EARTH_RADIUS, Checkpoint, Point, Step
from routing.ors import RouteOption
from trips.planner import MAX_DAYS_AHEAD, planTrip
from weather import openmeteo
from weather.openmeteo import WeatherReading, floorHour

MILES_PER_DEGREE = EARTH_RADIUS * 3.141592653589793 / 180
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
DEPARTURE = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
CHICAGO = (41.8781, -87.6298)
ST_LOUIS = (38.627, -90.1994)
ORS_FIXTURES = Path(__file__).parent / "fixtures" / "ors"

WeatherRule = Callable[[Checkpoint], WeatherReading | None]


def straightRoute(routeId: str, lon: float, miles: float, hours: float) -> RouteOption:
    """A route running due north along one longitude, so tests can target it by `lon`.

    Lengths avoid exact multiples of the interval until checkpoints get an
    end-of-route tolerance (see the xfail in test_checkpoints.py).
    """
    start = (38.0, lon)
    end = (38.0 + miles / MILES_PER_DEGREE, lon)
    return RouteOption(routeId, [start, end], [Step(0, 1, hours * 3600)], miles, hours * 3600)


def weather(wind: float = 5.0, rain: float = 0.0, snow: float = 0.0) -> WeatherRule:
    def rule(checkpoint: Checkpoint) -> WeatherReading:
        return WeatherReading(wind, wind + 5, rain, snow, floorHour(checkpoint.eta))

    return rule


class FakeServices:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.routes: list[RouteOption] = [
            straightRoute("A", -90.0, 302, 7.0),
            straightRoute("B", -88.0, 332, 8.0),
        ]
        self.places: dict[str, tuple[Point, str]] = {
            "Chicago": (CHICAGO, "Chicago, IL, USA"),
            "St. Louis": (ST_LOUIS, "St. Louis, MO, USA"),
        }
        self.rule: WeatherRule = weather()
        self.weatherCalls: list[list[Checkpoint]] = []
        self.geocodeCalls: list[str] = []
        monkeypatch.setattr(ors, "geocode", self.geocode)
        monkeypatch.setattr(ors, "getRouteOptions", self.getRouteOptions)
        monkeypatch.setattr(openmeteo, "weatherForCheckpoints", self.weatherForCheckpoints)

    def geocode(self, text: str) -> tuple[Point, str]:
        self.geocodeCalls.append(text)
        return self.places[text]

    def getRouteOptions(self, origin: Point, destination: Point) -> list[RouteOption]:
        return self.routes

    def weatherForCheckpoints(
        self, checkpoints: list[Checkpoint], now: datetime | None = None
    ) -> list[WeatherReading | None]:
        self.weatherCalls.append(checkpoints)
        readings = []
        for checkpoint in checkpoints:
            readings.append(self.rule(checkpoint))
        return readings


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> FakeServices:
    return FakeServices(monkeypatch)


def plan(services: FakeServices, loadLb: float = 20_000, **overrides: object):
    args: dict = {
        "originText": "Chicago",
        "destinationText": "St. Louis",
        "departure": DEPARTURE,
        "loadLb": loadLb,
        "interval": 25,
        "now": NOW,
    }
    args.update(overrides)
    return planTrip(**args)


def onRoute(lon: float, stormy: WeatherRule, calm: WeatherRule | None = None) -> WeatherRule:
    calm = calm or weather()

    def rule(checkpoint: Checkpoint) -> WeatherReading | None:
        return stormy(checkpoint) if abs(checkpoint.lon - lon) < 0.01 else calm(checkpoint)

    return rule


# --- happy path ---------------------------------------------------------------


def testCalmWeatherRecommendsTheFasterRoute(services: FakeServices) -> None:
    result = plan(services)
    assert [route.routeId for route in result.routes] == ["A", "B"]
    assert result.recommendedRouteId == "A"
    assert (
        result.reason == "Route A recommended over Route B: shorter travel time (7.0 h vs 8.0 h)."
    )
    for route in result.routes:
        for checkpoint in route.checkpoints:
            assert checkpoint.risk == RiskLevel.LOW


def testPlanCarriesInputsAndPlaces(services: FakeServices) -> None:
    result = plan(services)
    assert result.originLabel == "Chicago, IL, USA"
    assert result.destinationLabel == "St. Louis, MO, USA"
    assert result.origin == CHICAGO
    assert result.departure == DEPARTURE
    assert result.loadLb == 20_000
    assert result.interval == 25


def testCheckpointsCarryEtaWeatherAndRisk(services: FakeServices) -> None:
    route = plan(services).routes[0]
    expectedMiles = [0, 25, 50, 75, 100, 125, 150, 175, 200, 225, 250, 275, 300, 302]
    assert [round(c.mile) for c in route.checkpoints] == expectedMiles
    first, last = route.checkpoints[0], route.checkpoints[-1]
    assert first.eta == DEPARTURE
    assert last.eta == DEPARTURE + timedelta(hours=7)
    assert first.weather.windMph == 5.0
    assert route.totalMiles == pytest.approx(last.mile)


def testWeatherIsFetchedOnceForAllRoutes(services: FakeServices) -> None:
    result = plan(services)
    assert len(services.weatherCalls) == 1
    total = 0
    for route in result.routes:
        total += len(route.checkpoints)
    assert len(services.weatherCalls[0]) == total


def testSummaryMatchesTheRoute(services: FakeServices) -> None:
    for route in plan(services).routes:
        assert route.summary.routeId == route.routeId
        assert route.summary.totalMiles == pytest.approx(route.totalMiles)
        assert sum(route.summary.milesPerRiskLvl.values()) == pytest.approx(route.totalMiles)


# --- weather and load change the decision ---------------------------------------


def testStormOnTheFasterRouteFlipsTheRecommendation(services: FakeServices) -> None:
    services.rule = onRoute(-90.0, weather(wind=50))
    result = plan(services, loadLb=10_000)
    assert result.recommendedRouteId == "B"
    assert result.reason.startswith("Route B recommended over Route A: fewer severe miles")
    assert result.routes[1].checkpoints[0].risk == RiskLevel.SEVERE


@pytest.mark.parametrize(
    ("loadLb", "expected"),
    [(20_000, RiskLevel.HIGH), (45_000, RiskLevel.SEVERE)],
)
def testLoadWeightChangesTheRisk(
    services: FakeServices, loadLb: float, expected: RiskLevel
) -> None:
    services.rule = weather(wind=40)
    route = plan(services, loadLb=loadLb).routes[0]
    assert route.checkpoints[0].risk == expected


def testRainAndSnowAreClassified(services: FakeServices) -> None:
    services.rule = onRoute(-90.0, weather(rain=0.3), weather(snow=2.5))
    result = plan(services)
    byId = {route.routeId: route for route in result.routes}
    assert byId["A"].checkpoints[0].risk == RiskLevel.HIGH
    assert byId["B"].checkpoints[0].risk == RiskLevel.SEVERE
    assert result.recommendedRouteId == "A"


def testNoDrivableRoute(services: FakeServices) -> None:
    services.rule = weather(wind=60)
    result = plan(services)
    assert result.recommendedRouteId is None
    assert result.reason == "No route is safe to drive at this departure time."
    assert len(result.routes) == 2  # still returned so the map can show why


# --- missing weather is never treated as safe ------------------------------------


def testMissingWeatherStopsThePlan(services: FakeServices) -> None:
    calm = weather()

    def gap(checkpoint: Checkpoint) -> WeatherReading | None:
        return None if checkpoint.mile > 200 else calm(checkpoint)

    services.rule = gap
    with pytest.raises(ValueError, match="forecast is not available"):
        plan(services)


# --- validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"loadLb": -1}, "negative", id="negative load"),
        pytest.param(
            {"departure": datetime(2026, 10, 14, 10, 0)}, "timezone", id="naive departure"
        ),
        pytest.param({"departure": NOW - timedelta(hours=2)}, "past", id="departure in the past"),
        pytest.param(
            {"departure": NOW + timedelta(days=MAX_DAYS_AHEAD, hours=1)},
            "within",
            id="too far ahead",
        ),
    ],
)
def testBadRequestsAreRejectedBeforeAnyApiCall(
    services: FakeServices, overrides: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        plan(services, **overrides)
    assert services.geocodeCalls == []


def testDepartureALittleInThePastIsAccepted(services: FakeServices) -> None:
    assert plan(services, departure=NOW - timedelta(minutes=30)).recommendedRouteId == "A"


def testDepartureInAnotherTimezone(services: FakeServices) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    result = plan(services, departure=datetime(2026, 10, 14, 15, 30, tzinfo=ist))
    assert result.routes[0].checkpoints[0].eta == DEPARTURE


def testUnsupportedIntervalIsRejected(services: FakeServices) -> None:
    with pytest.raises(ValueError, match="Interval"):
        plan(services, interval=15)


def testSamePlaceIsRejected(services: FakeServices) -> None:
    services.places["Chicago Loop"] = ((41.8800, -87.6300), "Chicago Loop, IL, USA")
    with pytest.raises(ValueError, match="same place"):
        plan(services, destinationText="Chicago Loop")


# --- real route geometry --------------------------------------------------------


def testRealOrsRoutesFlowThroughThePlanner(services: FakeServices) -> None:
    direct = json.loads((ORS_FIXTURES / "directions_long_direct.json").read_text())["features"][0]
    via = json.loads((ORS_FIXTURES / "directions_long_via.json").read_text())["features"][0]
    services.routes = [ors.parseRoute(direct, "A"), ors.parseRoute(via, "B")]

    result = plan(services)
    byId = {route.routeId: route for route in result.routes}
    assert len(byId["A"].checkpoints) == 14  # 0, 25 ... 300, then 301.3
    assert len(byId["B"].checkpoints) == 15
    assert byId["A"].totalMiles == pytest.approx(301.3, abs=0.1)
    assert result.recommendedRouteId == "A"
    assert byId["A"].checkpoints[-1].eta == DEPARTURE + timedelta(
        seconds=byId["A"].checkpoints[-1].secondsFromStart
    )


def testRouteLengthComesFromTheCheckpointsNotTheOrsSummary(services: FakeServices) -> None:
    """If ORS's summary distance and the geometry disagree, scoring follows the geometry."""
    geometry = straightRoute("A", -90.0, 302, 7.0)
    services.routes = [
        RouteOption("A", geometry.points, geometry.steps, 310.0, geometry.totalSeconds)
    ]
    route = plan(services).routes[0]
    assert route.totalMiles == pytest.approx(302)
    assert sum(route.summary.milesPerRiskLvl.values()) == pytest.approx(302)
