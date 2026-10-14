import json
import logging
from datetime import datetime

import httpx
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from risk.engine import RiskLevel
from routing import ors
from routing.ors import OrsError
from trips import heatmap, planner
from trips.heatmap import Heatmap
from trips.planner import PlannedCheckpoint, PlannedRoute, TripPlan
from weather.openmeteo import WeatherError

logger = logging.getLogger(__name__)

MIN_QUERY_LENGTH = 2
COORDINATE_DECIMALS = 5


def errorResponse(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def serializeCheckpoint(checkpoint: PlannedCheckpoint) -> dict:
    weather = checkpoint.weather
    return {
        "mile": round(checkpoint.mile, 2),
        "lat": round(checkpoint.lat, COORDINATE_DECIMALS),
        "lon": round(checkpoint.lon, COORDINATE_DECIMALS),
        "secondsFromStart": round(checkpoint.secondsFromStart),
        "eta": checkpoint.eta.replace(microsecond=0).isoformat(),
        "risk": checkpoint.risk.name,
        "weather": {
            "windMph": weather.windMph,
            "gustMph": weather.gustMph,
            "rainInHr": weather.rainInHr,
            "snowInHr": weather.snowInHr,
            "forecastHour": weather.forecastHour.isoformat(),
        },
    }


def serializeRoute(route: PlannedRoute, rank: int, recommendedRouteId: str | None) -> dict:
    milesPerRiskLevel = {}
    for level, miles in route.summary.milesPerRiskLvl.items():
        milesPerRiskLevel[level.name] = round(miles, 2)

    geometry = []
    for lat, lon in route.points:
        geometry.append([round(lat, COORDINATE_DECIMALS), round(lon, COORDINATE_DECIMALS)])

    checkpoints = []
    for checkpoint in route.checkpoints:
        checkpoints.append(serializeCheckpoint(checkpoint))

    return {
        "routeId": route.routeId,
        "rank": rank,
        "recommended": route.routeId == recommendedRouteId,
        "totalMiles": round(route.totalMiles, 2),
        "totalSeconds": round(route.totalSeconds),
        "summary": {
            "milesPerRiskLevel": milesPerRiskLevel,
            "avgRisk": round(route.summary.avgRisk, 3),
            "drivable": route.summary.drivable,
        },
        "geometry": geometry,
        "checkpoints": checkpoints,
    }


def serializeTrip(plan: TripPlan) -> dict:
    routes = []
    for i in range(len(plan.routes)):
        routes.append(serializeRoute(plan.routes[i], i + 1, plan.recommendedRouteId))

    return {
        "origin": {"label": plan.originLabel, "lat": plan.origin[0], "lon": plan.origin[1]},
        "destination": {
            "label": plan.destinationLabel,
            "lat": plan.destination[0],
            "lon": plan.destination[1],
        },
        "departure": plan.departure.isoformat(),
        "loadLb": plan.loadLb,
        "interval": plan.interval,
        "recommendedRouteId": plan.recommendedRouteId,
        "reason": plan.reason,
        "routes": routes,
    }


def parseJsonObject(body: bytes, fields: list[str]) -> dict:
    try:
        data = json.loads(body)
    except ValueError as error:
        raise ValueError("Request body must be valid JSON") from error
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")

    for field in fields:
        if field not in data:
            raise ValueError(f"Missing field '{field}'")
    return data


def requirePlace(data: dict, field: str) -> str:
    if not isinstance(data[field], str) or not data[field].strip():
        raise ValueError(f"'{field}' must be a place name")
    return data[field].strip()


def requireNumber(data: dict, field: str) -> float:
    if isinstance(data[field], bool) or not isinstance(data[field], int | float):
        raise ValueError(f"'{field}' must be a number")
    return data[field]


def parsePlanRequest(body: bytes) -> dict:
    data = parseJsonObject(body, ["origin", "destination", "departure", "loadLb", "interval"])
    originText = requirePlace(data, "origin")
    destinationText = requirePlace(data, "destination")
    loadLb = float(requireNumber(data, "loadLb"))
    interval = requireNumber(data, "interval")

    if not isinstance(data["departure"], str):
        raise ValueError("'departure' must be an ISO 8601 date-time string")
    try:
        departure = datetime.fromisoformat(data["departure"])
    except ValueError as error:
        raise ValueError(
            "'departure' must be an ISO 8601 date-time, e.g. 2026-10-14T10:00:00Z"
        ) from error

    return {
        "originText": originText,
        "destinationText": destinationText,
        "departure": departure,
        "loadLb": loadLb,
        "interval": interval,
    }


def parseHeatmapRequest(body: bytes) -> dict:
    data = parseJsonObject(body, ["origin", "destination", "loadLb"])
    return {
        "originText": requirePlace(data, "origin"),
        "destinationText": requirePlace(data, "destination"),
        "loadLb": float(requireNumber(data, "loadLb")),
    }


def serializeHeatmap(result: Heatmap) -> dict:
    points = []
    for lat, lon in result.points:
        points.append([round(lat, COORDINATE_DECIMALS), round(lon, COORDINATE_DECIMALS)])

    levels = []
    for level in RiskLevel:
        levels.append(level.name)

    # risk as level numbers (index into `levels`) to keep the 49 frames small
    risk = []
    for row in result.risk:
        numbers = []
        for level in row:
            numbers.append(None if level is None else int(level))
        risk.append(numbers)

    return {
        "startHour": result.startHour.isoformat(),
        "hours": len(result.risk),
        "levels": levels,
        "points": points,
        "risk": risk,
    }


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_GET
def geocode(request: HttpRequest) -> JsonResponse:
    query = str(request.GET.get("q", "")).strip()
    if len(query) < MIN_QUERY_LENGTH:
        return JsonResponse({"results": []})

    try:
        matches = ors.autocomplete(query)
    except (OrsError, httpx.HTTPError):
        logger.exception("Geocoding failed for %r", query)
        return errorResponse("Place search is unavailable right now, try again", 502)

    results = []
    for (lat, lon), label in matches:
        results.append({"label": label, "lat": lat, "lon": lon})
    return JsonResponse({"results": results})


@require_POST
def planTripView(request: HttpRequest) -> JsonResponse:
    try:
        args = parsePlanRequest(request.body)
        plan = planner.planTrip(**args)
    except (OrsError, WeatherError, httpx.HTTPError) as error:
        logger.exception("Upstream service failed while planning a trip")
        return errorResponse(f"A routing or weather service failed: {error}", 502)
    except ValueError as error:
        return errorResponse(str(error), 400)
    except Exception:
        logger.exception("Unexpected error while planning a trip")
        return errorResponse("Something went wrong while planning the trip", 500)

    return JsonResponse(serializeTrip(plan))


@require_POST
def heatmapView(request: HttpRequest) -> JsonResponse:
    try:
        args = parseHeatmapRequest(request.body)
        result = heatmap.buildHeatmap(**args)
    except (OrsError, WeatherError, httpx.HTTPError) as error:
        logger.exception("Upstream service failed while building a heatmap")
        return errorResponse(f"A routing or weather service failed: {error}", 502)
    except ValueError as error:
        return errorResponse(str(error), 400)
    except Exception:
        logger.exception("Unexpected error while building a heatmap")
        return errorResponse("Something went wrong while building the heatmap", 500)

    return JsonResponse(serializeHeatmap(result))
