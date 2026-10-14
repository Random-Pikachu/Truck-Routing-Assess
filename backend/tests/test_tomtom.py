import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from routing import ors, provider, tomtom
from routing.checkpoints import Step, checkpointGenerator
from routing.ors import OrsError, RouteOption
from routing.tomtom import EMPTY_TRUCK_LB, LB_PER_KG, TomTomError, grossWeightKg, parseRoute

FIXTURES = Path(__file__).parent / "fixtures" / "tomtom"
CHICAGO = (41.8781, -87.6298)
ST_LOUIS = (38.627, -90.1994)
DEPARTURE = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)


def loadFixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


ROUTES_BODY = loadFixture("route_chicago_stlouis.json")


class FakeGet:
    def __init__(self, body: dict, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params: dict, timeout: float) -> httpx.Response:
        self.calls.append((url, params))
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def tomtomKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOMTOM_API_KEY", "test-key")


def orsRoutes(count: int) -> list[RouteOption]:
    routes = []
    for i in range(count):
        routes.append(RouteOption("ABC"[i], [CHICAGO, ST_LOUIS], [Step(0, 1, 3600)], 260, 3600))
    return routes


# ---------- parsing ----------


def testParseRouteReadsPointsDistanceAndTime() -> None:
    route = parseRoute(ROUTES_BODY["routes"][0], "A")
    assert route.routeId == "A"
    assert len(route.points) == 136
    assert route.points[0] == pytest.approx(CHICAGO, abs=1e-3)
    assert route.points[-1] == pytest.approx(ST_LOUIS, abs=1e-2)
    assert route.totalMiles == pytest.approx(547589 / 1609.344)
    assert route.totalSeconds == 17649


@pytest.mark.parametrize("index", [0, 1, 2])
def testStepsCoverTheWholeRouteWithoutGaps(index: int) -> None:
    route = parseRoute(ROUTES_BODY["routes"][index], "A")
    assert route.steps[0].startIndex == 0
    assert route.steps[-1].endIndex == len(route.points) - 1
    for i in range(1, len(route.steps)):
        assert route.steps[i].startIndex == route.steps[i - 1].endIndex
        assert route.steps[i].startIndex < route.steps[i].endIndex


@pytest.mark.parametrize("index", [0, 1, 2])
def testStepDurationsAddUpToTheRouteTime(index: int) -> None:
    route = parseRoute(ROUTES_BODY["routes"][index], "A")
    total = 0.0
    for step in route.steps:
        total += step.durationSeconds
    assert total == pytest.approx(route.totalSeconds)


def testParsedRouteWorksWithTheCheckpointGenerator() -> None:
    route = parseRoute(ROUTES_BODY["routes"][0], "A")
    checkpoints = checkpointGenerator(route.points, route.steps, DEPARTURE, 25)
    assert checkpoints[0].secondsFromStart == 0
    assert checkpoints[-1].secondsFromStart == pytest.approx(route.totalSeconds)
    for i in range(1, len(checkpoints)):
        assert checkpoints[i].secondsFromStart > checkpoints[i - 1].secondsFromStart


def testInstructionsEndingBeforeTheLastPointGetAClosingStep() -> None:
    raw = {
        "summary": {"lengthInMeters": 3000, "travelTimeInSeconds": 300},
        "legs": [{"points": [{"latitude": 0, "longitude": i / 100} for i in range(4)]}],
        "guidance": {
            "instructions": [
                {"pointIndex": 0, "travelTimeInSeconds": 0},
                {"pointIndex": 2, "travelTimeInSeconds": 200},
            ]
        },
    }
    route = parseRoute(raw, "A")
    assert route.steps == [Step(0, 2, 200), Step(2, 3, 100)]


def testRouteWithoutInstructionsIsOneStep() -> None:
    raw = {
        "summary": {"lengthInMeters": 3000, "travelTimeInSeconds": 300},
        "legs": [{"points": [{"latitude": 0, "longitude": i / 100} for i in range(4)]}],
    }
    assert parseRoute(raw, "A").steps == [Step(0, 3, 300)]


def testGrossWeightAddsAnEmptyTruckToTheLoad() -> None:
    assert grossWeightKg(0) == round(EMPTY_TRUCK_LB / LB_PER_KG)
    assert grossWeightKg(45000) == round(80000 / LB_PER_KG)


# ---------- requests ----------


def testRequestsThreeTruckRoutesWithLoadAndDeparture(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGet(ROUTES_BODY)
    monkeypatch.setattr(tomtom.httpx, "get", fake)

    routes = tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 45000)

    assert [route.routeId for route in routes] == ["A", "B", "C"]
    url, params = fake.calls[0]
    assert url.endswith("/41.8781,-87.6298:38.627,-90.1994/json")
    assert params["travelMode"] == "truck"
    assert params["maxAlternatives"] == 2
    assert params["vehicleWeight"] == grossWeightKg(45000)
    assert params["departAt"] == "2026-10-16T14:00:00+00:00"
    assert params["key"] == "test-key"


def testNoDepartureLetsTomTomUseNow(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGet(ROUTES_BODY)
    monkeypatch.setattr(tomtom.httpx, "get", fake)
    tomtom.getRouteOptions(CHICAGO, ST_LOUIS, None, 0)
    assert "departAt" not in fake.calls[0][1]


def testRoutesAreCachedPerDepartureHourAndWeight(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGet(ROUTES_BODY)
    monkeypatch.setattr(tomtom.httpx, "get", fake)

    tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 30000)
    tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE.replace(minute=40), 30000)
    assert len(fake.calls) == 1

    tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE.replace(hour=15), 30000)
    tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 45000)
    assert len(fake.calls) == 3


def testHttpErrorRaisesTomTomErrorWithItsMessage(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"detailedError": {"code": "MAP_MATCHING_FAILURE", "message": "Origin (30, -40)"}}
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(body, status=400))
    with pytest.raises(TomTomError, match="400: Origin"):
        tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)


def testEmptyRouteListIsAnError(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet({"routes": []}))
    with pytest.raises(TomTomError):
        tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)


def testErrorsAreNotCached(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet({}, status=503))
    with pytest.raises(TomTomError):
        tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)

    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(ROUTES_BODY))
    assert len(tomtom.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)) == 3


# ---------- provider: TomTom first, ORS as fallback ----------


class FakeOrs:
    def __init__(self, routes: list[RouteOption] | None = None, error: Exception | None = None):
        self.routes = routes or []
        self.error = error
        self.calls = 0

    def __call__(self, origin: object, destination: object) -> list[RouteOption]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.routes


def testWithoutAKeyOnlyOrsIsUsed(monkeypatch: pytest.MonkeyPatch) -> None:
    fakeOrs = FakeOrs(orsRoutes(3))
    monkeypatch.setattr(ors, "getRouteOptions", fakeOrs)

    def failIfCalled(*args: object, **kwargs: object) -> None:
        raise AssertionError("TomTom should not be called without a key")

    monkeypatch.setattr(tomtom.httpx, "get", failIfCalled)
    assert provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0) == fakeOrs.routes


def testThreeTomTomRoutesSkipOrs(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fakeOrs = FakeOrs(orsRoutes(3))
    monkeypatch.setattr(ors, "getRouteOptions", fakeOrs)
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(ROUTES_BODY))

    routes = provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)
    assert len(routes) == 3
    assert routes[0].totalSeconds == 17649
    assert fakeOrs.calls == 0


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            FakeGet({"detailedError": {"message": "Forbidden"}}, status=403), id="bad key"
        ),
        pytest.param(FakeGet({"routes": [{"summary": {}}]}), id="unexpected body"),
    ],
)
def testTomTomFailureFallsBackToOrs(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch, failure: FakeGet
) -> None:
    fakeOrs = FakeOrs(orsRoutes(3))
    monkeypatch.setattr(ors, "getRouteOptions", fakeOrs)
    monkeypatch.setattr(tomtom.httpx, "get", failure)
    assert provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0) == fakeOrs.routes


def testNetworkErrorFallsBackToOrs(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fakeOrs = FakeOrs(orsRoutes(3))
    monkeypatch.setattr(ors, "getRouteOptions", fakeOrs)

    def timeout(*args: object, **kwargs: object) -> None:
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(tomtom.httpx, "get", timeout)
    assert provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0) == fakeOrs.routes


def oneRouteBody() -> dict:
    return {"routes": ROUTES_BODY["routes"][:1]}


def testFewerTomTomRoutesUseOrsWhenItFindsMore(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeOrs = FakeOrs(orsRoutes(3))
    monkeypatch.setattr(ors, "getRouteOptions", fakeOrs)
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(oneRouteBody()))
    assert provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0) == fakeOrs.routes


def testFewerTomTomRoutesAreKeptWhenOrsHasNoMore(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ors, "getRouteOptions", FakeOrs(orsRoutes(1)))
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(oneRouteBody()))
    routes = provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)
    assert len(routes) == 1
    assert routes[0].totalSeconds == 17649


def testFewerTomTomRoutesAreKeptWhenOrsFails(
    tomtomKey: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ors, "getRouteOptions", FakeOrs(error=OrsError(503, "busy")))
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet(oneRouteBody()))
    assert len(provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)) == 1


def testBothFailingRaisesTheOrsError(tomtomKey: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ors, "getRouteOptions", FakeOrs(error=OrsError(503, "busy")))
    monkeypatch.setattr(tomtom.httpx, "get", FakeGet({}, status=500))
    with pytest.raises(OrsError):
        provider.getRouteOptions(CHICAGO, ST_LOUIS, DEPARTURE, 0)
