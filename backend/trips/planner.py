from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from risk.engine import RiskLevel, classify
from risk.scoring import RouteSummary, generateRouteSummary, recommendRoute
from routing import ors
from routing.checkpoints import Checkpoint, Point, checkpointGenerator, haversine
from weather import openmeteo
from weather.openmeteo import WeatherReading

MAX_DAYS_AHEAD = 14
PAST_DEPARTURE_TOLERANCE = timedelta(hours=1)
SAME_PLACE_MILES = 0.5


@dataclass(frozen=True)
class PlannedCheckpoint:
    mile: float
    lat: float
    lon: float
    secondsFromStart: float
    eta: datetime
    weather: WeatherReading
    risk: RiskLevel


@dataclass(frozen=True)
class PlannedRoute:
    routeId: str
    points: list[Point]
    totalMiles: float
    totalSeconds: float
    checkpoints: list[PlannedCheckpoint]
    summary: RouteSummary


@dataclass(frozen=True)
class TripPlan:
    originLabel: str
    origin: Point
    destinationLabel: str
    destination: Point
    departure: datetime
    loadLb: float
    interval: float
    routes: list[PlannedRoute]  # best first
    recommendedRouteId: str | None  # None when no route is drivable
    reason: str


def validateRequest(departure: datetime, loadLb: float, now: datetime) -> None:
    if loadLb < 0:
        raise ValueError("Load weight can't be negative")
    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be a timezone-aware datetime")
    if departure < now - PAST_DEPARTURE_TOLERANCE:
        raise ValueError("Departure time is in the past")
    if departure > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError(
            f"Departure must be within {MAX_DAYS_AHEAD} days, the weather forecast ends after that"
        )


def planTrip(
    originText: str,
    destinationText: str,
    departure: datetime,
    loadLb: float,
    interval: float,
    now: datetime | None = None,
) -> TripPlan:
    now = now or datetime.now(UTC)
    validateRequest(departure, loadLb, now)

    origin, originLabel = ors.geocode(originText)
    destination, destinationLabel = ors.geocode(destinationText)
    if haversine(origin, destination) < SAME_PLACE_MILES:
        raise ValueError("Origin and destination are the same place")

    routes = ors.getRouteOptions(origin, destination)

    checkpointsPerRoute: list[list[Checkpoint]] = []
    allCheckpoints: list[Checkpoint] = []
    for route in routes:
        checkpoints = checkpointGenerator(route.points, route.steps, departure, interval)
        checkpointsPerRoute.append(checkpoints)
        allCheckpoints.extend(checkpoints)

    # one weather call for all routes, so shared stretches are fetched once
    readings = openmeteo.weatherForCheckpoints(allCheckpoints, now=now)
    for reading in readings:
        if reading is None:
            raise ValueError(
                "Weather forecast is not available for the whole trip, try an earlier departure"
            )

    plannedById: dict[str, PlannedRoute] = {}
    summaries: list[RouteSummary] = []
    k = 0
    for r in range(len(routes)):
        route = routes[r]
        checkpoints = checkpointsPerRoute[r]

        planned = []
        miles = []
        levels = []
        for checkpoint in checkpoints:
            reading = readings[k]
            k += 1
            assert reading is not None
            level = classify(reading.windMph, reading.rainInHr, reading.snowInHr, loadLb)
            planned.append(
                PlannedCheckpoint(
                    mile=checkpoint.mile,
                    lat=checkpoint.lat,
                    lon=checkpoint.lon,
                    secondsFromStart=checkpoint.secondsFromStart,
                    eta=checkpoint.eta,
                    weather=reading,
                    risk=level,
                )
            )
            miles.append(checkpoint.mile)
            levels.append(level)

        # route length from the checkpoints so owned miles line up with checkpoint miles
        totalMiles = checkpoints[-1].mile
        summary = generateRouteSummary(route.routeId, miles, levels, totalMiles, route.totalSeconds)
        summaries.append(summary)
        plannedById[route.routeId] = PlannedRoute(
            routeId=route.routeId,
            points=route.points,
            totalMiles=totalMiles,
            totalSeconds=route.totalSeconds,
            checkpoints=planned,
            summary=summary,
        )

    ranked, reason = recommendRoute(summaries)

    rankedRoutes = []
    for summary in ranked:
        rankedRoutes.append(plannedById[summary.routeId])

    return TripPlan(
        originLabel=originLabel,
        origin=origin,
        destinationLabel=destinationLabel,
        destination=destination,
        departure=departure,
        loadLb=loadLb,
        interval=interval,
        routes=rankedRoutes,
        recommendedRouteId=ranked[0].routeId if ranked[0].drivable else None,
        reason=reason,
    )
