import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.test import Client

from risk.engine import RiskLevel
from risk.scoring import RouteSummary
from routing import ors
from routing.ors import OrsError
from trips import planner
from trips.planner import PlannedCheckpoint, PlannedRoute, TripPlan
from weather.openmeteo import WeatherError, WeatherReading

DEPARTURE = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
VALID_BODY = {
    "origin": "Chicago, IL",
    "destination": "St. Louis, MO",
    "departure": "2026-10-14T10:00:00Z",
    "loadLb": 42000,
    "interval": 25,
}


def plannedCheckpoint(mile: float, hours: float, risk: RiskLevel) -> PlannedCheckpoint:
    forecastHour = DEPARTURE + timedelta(hours=hours)
    eta = forecastHour + timedelta(microseconds=834104)  # real ETAs are not whole seconds
    reading = WeatherReading(12.0, 20.0, 0.0, 0.0, forecastHour)
    return PlannedCheckpoint(mile, 41.123456789, -87.987654321, hours * 3600, eta, reading, risk)


def plannedRoute(routeId: str, risk: RiskLevel, drivable: bool = True) -> PlannedRoute:
    miles = {level: 0.0 for level in RiskLevel}
    miles[risk] = 50.0
    summary = RouteSummary(routeId, 50.0, 3600.0, miles, float(risk), drivable)
    checkpoints = [plannedCheckpoint(0, 0, RiskLevel.LOW), plannedCheckpoint(50, 1, risk)]
    return PlannedRoute(
        routeId, [(41.123456789, -87.987654321), (40.5, -88.5)], 50.0, 3600.0, checkpoints, summary
    )


def tripPlan(recommendedRouteId: str | None = "A") -> TripPlan:
    return TripPlan(
        originLabel="Chicago, IL, USA",
        origin=(41.87897, -87.66063),
        destinationLabel="St. Louis, MO, USA",
        destination=(38.627, -90.1994),
        departure=DEPARTURE,
        loadLb=42000.0,
        interval=25,
        routes=[plannedRoute("A", RiskLevel.LOW), plannedRoute("B", RiskLevel.SEVERE)],
        recommendedRouteId=recommendedRouteId,
        reason="Route A recommended over Route B: fewer severe miles (0.0 vs 50.0).",
    )


class FakePlanner:
    def __init__(self, result: object = None) -> None:
        self.result = result if result is not None else tripPlan()
        self.calls: list[dict] = []

    def __call__(self, **kwargs: object) -> TripPlan:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        assert isinstance(self.result, TripPlan)
        return self.result


@pytest.fixture
def fakePlanner(monkeypatch: pytest.MonkeyPatch) -> FakePlanner:
    fake = FakePlanner()
    monkeypatch.setattr(planner, "planTrip", fake)
    return fake


def postPlan(client: Client, body: object) -> httpx.Response:
    payload = body if isinstance(body, str) else json.dumps(body)
    return client.post("/api/trips/plan", data=payload, content_type="application/json")


# --- health -------------------------------------------------------------------


def testHealth(client: Client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- plan: request parsing ------------------------------------------------------


def testPlanPassesParsedValuesToThePlanner(client: Client, fakePlanner: FakePlanner) -> None:
    response = postPlan(client, VALID_BODY)
    assert response.status_code == 200
    call = fakePlanner.calls[0]
    assert call["originText"] == "Chicago, IL"
    assert call["destinationText"] == "St. Louis, MO"
    assert call["departure"] == DEPARTURE
    assert call["departure"].tzinfo is not None
    assert call["loadLb"] == 42000.0
    assert call["interval"] == 25


def testPlanAcceptsOffsetTimestamps(client: Client, fakePlanner: FakePlanner) -> None:
    postPlan(client, {**VALID_BODY, "departure": "2026-10-14T15:30:00+05:30"})
    assert fakePlanner.calls[0]["departure"] == DEPARTURE


@pytest.mark.parametrize(
    ("body", "message"),
    [
        pytest.param("{not json", "valid JSON", id="invalid json"),
        pytest.param("[1, 2]", "JSON object", id="not an object"),
        pytest.param({**VALID_BODY, "origin": "  "}, "place name", id="blank origin"),
        pytest.param({**VALID_BODY, "destination": 7}, "place name", id="destination not text"),
        pytest.param({**VALID_BODY, "loadLb": "heavy"}, "number", id="load not a number"),
        pytest.param({**VALID_BODY, "loadLb": True}, "number", id="load is a boolean"),
        pytest.param({**VALID_BODY, "interval": None}, "number", id="interval missing value"),
        pytest.param(
            {**VALID_BODY, "departure": "tomorrow"}, "ISO 8601", id="unparseable departure"
        ),
        pytest.param({**VALID_BODY, "departure": 1700000000}, "ISO 8601", id="departure not text"),
    ],
)
def testPlanRejectsBadBodiesBeforePlanning(
    client: Client, fakePlanner: FakePlanner, body: object, message: str
) -> None:
    response = postPlan(client, body)
    assert response.status_code == 400
    assert message in response.json()["error"]
    assert fakePlanner.calls == []


@pytest.mark.parametrize("field", ["origin", "destination", "departure", "loadLb", "interval"])
def testPlanRejectsMissingFields(client: Client, fakePlanner: FakePlanner, field: str) -> None:
    body = dict(VALID_BODY)
    del body[field]
    response = postPlan(client, body)
    assert response.status_code == 400
    assert field in response.json()["error"]


def testPlanOnlyAcceptsPost(client: Client) -> None:
    assert client.get("/api/trips/plan").status_code == 405


# --- plan: errors from the planner -------------------------------------------------


def testPlannerValidationErrorIsA400(client: Client, fakePlanner: FakePlanner) -> None:
    fakePlanner.result = ValueError("Departure time is in the past")
    response = postPlan(client, VALID_BODY)
    assert response.status_code == 400
    assert response.json() == {"error": "Departure time is in the past"}


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(OrsError(2010, "Could not find routable point"), id="ORS error"),
        pytest.param(WeatherError("Open-Meteo error 503: busy"), id="weather error"),
        pytest.param(httpx.ConnectError("no network"), id="network error"),
    ],
)
def testUpstreamFailuresAreA502(
    client: Client, fakePlanner: FakePlanner, failure: Exception
) -> None:
    fakePlanner.result = failure
    response = postPlan(client, VALID_BODY)
    assert response.status_code == 502
    assert "service failed" in response.json()["error"]


def testUnexpectedErrorsAreA500WithoutDetails(client: Client, fakePlanner: FakePlanner) -> None:
    fakePlanner.result = KeyError("secret internal detail")
    response = postPlan(client, VALID_BODY)
    assert response.status_code == 500
    assert "secret" not in response.json()["error"]


# --- plan: response shape ----------------------------------------------------------


def testPlanResponseShape(client: Client, fakePlanner: FakePlanner) -> None:
    data = postPlan(client, VALID_BODY).json()
    assert data["origin"] == {"label": "Chicago, IL, USA", "lat": 41.87897, "lon": -87.66063}
    assert data["departure"] == "2026-10-14T10:00:00+00:00"
    assert data["recommendedRouteId"] == "A"
    assert data["reason"].startswith("Route A recommended")
    assert [route["routeId"] for route in data["routes"]] == ["A", "B"]


def testRouteShape(client: Client, fakePlanner: FakePlanner) -> None:
    routes = postPlan(client, VALID_BODY).json()["routes"]
    first, second = routes
    assert (first["rank"], first["recommended"]) == (1, True)
    assert (second["rank"], second["recommended"]) == (2, False)
    assert first["summary"]["milesPerRiskLevel"] == {
        "LOW": 50.0,
        "MODERATE": 0.0,
        "HIGH": 0.0,
        "SEVERE": 0.0,
        "NO_TRAVEL": 0.0,
    }
    assert second["summary"]["avgRisk"] == 3.0
    assert first["geometry"][0] == [41.12346, -87.98765]  # rounded to 5 decimals


def testCheckpointShape(client: Client, fakePlanner: FakePlanner) -> None:
    checkpoint = postPlan(client, VALID_BODY).json()["routes"][1]["checkpoints"][1]
    assert checkpoint["mile"] == 50
    assert checkpoint["eta"] == "2026-10-14T11:00:00+00:00"
    assert checkpoint["risk"] == "SEVERE"
    assert checkpoint["weather"] == {
        "windMph": 12.0,
        "gustMph": 20.0,
        "rainInHr": 0.0,
        "snowInHr": 0.0,
        "forecastHour": "2026-10-14T11:00:00+00:00",
    }


def testNoDrivableRouteHasNoRecommendedFlag(client: Client, fakePlanner: FakePlanner) -> None:
    fakePlanner.result = tripPlan(recommendedRouteId=None)
    data = postPlan(client, VALID_BODY).json()
    assert data["recommendedRouteId"] is None
    for route in data["routes"]:
        assert route["recommended"] is False


# --- geocode ----------------------------------------------------------------------


def testGeocodeReturnsSuggestions(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fakeAutocomplete(text: str, size: int = 5) -> list:
        calls.append(text)
        return [
            ((41.87897, -87.66063), "Chicago, IL, USA"),
            ((42.585, -87.819), "Chicago, Kenosha, WI, USA"),
        ]

    monkeypatch.setattr(ors, "autocomplete", fakeAutocomplete)
    response = client.get("/api/geocode", {"q": " Chica "})
    assert response.status_code == 200
    assert response.json()["results"][0] == {
        "label": "Chicago, IL, USA",
        "lat": 41.87897,
        "lon": -87.66063,
    }
    assert len(response.json()["results"]) == 2
    assert calls == ["Chica"]


@pytest.mark.parametrize("query", ["", "C", "  "])
def testGeocodeShortQueryMakesNoApiCall(
    client: Client, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    def failIfCalled(text: str, size: int = 5) -> list:
        raise AssertionError("autocomplete should not be called")

    monkeypatch.setattr(ors, "autocomplete", failIfCalled)
    response = client.get("/api/geocode", {"q": query})
    assert response.json() == {"results": []}


def testGeocodeUpstreamFailureIsA502(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(text: str, size: int = 5) -> list:
        raise OrsError(503, "busy")

    monkeypatch.setattr(ors, "autocomplete", broken)
    assert client.get("/api/geocode", {"q": "Chicago"}).status_code == 502


def testAutocompleteParsesOrsResponse(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "features": [
            {
                "geometry": {"coordinates": [-87.66063, 41.87897]},
                "properties": {"label": "Chicago, IL, USA"},
            },
        ]
    }
    sent: list[dict] = []

    def get(url: str, params: dict, timeout: float) -> httpx.Response:
        sent.append(params)
        return httpx.Response(200, json=body)

    monkeypatch.setenv("ORS_API_KEY", "test-key")
    monkeypatch.setattr(ors.httpx, "get", get)
    assert ors.autocomplete("Chica", size=3) == [((41.87897, -87.66063), "Chicago, IL, USA")]
    assert sent[0]["text"] == "Chica"
    assert sent[0]["size"] == 3


# --- CORS -----------------------------------------------------------------------


def testCorsAllowsTheFrontendDevServer(client: Client) -> None:
    response = client.options(
        "/api/trips/plan",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )
    assert response["Access-Control-Allow-Origin"] == "http://localhost:5173"


def testCorsBlocksOtherOrigins(client: Client) -> None:
    response = client.get("/api/health", HTTP_ORIGIN="https://evil.example")
    assert "Access-Control-Allow-Origin" not in response
