import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from django.core.cache import cache
from dotenv import load_dotenv

from routing.checkpoints import Point, Step
from routing.ors import METERS_PER_MILE, ROUTE_IDS, RouteOption

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOMTOM_ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute"
REQUEST_TIMEOUT_SECONDS = 30
LB_PER_KG = 2.20462

# TomTom wants the gross vehicle weight but the brief only gives the load,
# so a typical empty tractor-trailer is added on top of it
EMPTY_TRUCK_LB = 35000

# travel times include traffic, so they go stale faster than ORS routes
ROUTES_CACHE_SECONDS = 60 * 60


class TomTomError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"TomTom error {status}: {message}")
        self.status = status


def getApiKey() -> str:
    return os.environ.get("TOMTOM_API_KEY", "").strip()


def hasApiKey() -> bool:
    return getApiKey() != ""


def readError(response: httpx.Response) -> TomTomError:
    try:
        error = response.json().get("detailedError", {})
    except ValueError:
        return TomTomError(response.status_code, response.text[:200])

    if isinstance(error, dict):
        return TomTomError(response.status_code, error.get("message", ""))
    return TomTomError(response.status_code, str(error))


def grossWeightKg(loadLb: float) -> int:
    return round((EMPTY_TRUCK_LB + loadLb) / LB_PER_KG)


def parseRoute(route: dict, routeId: str) -> RouteOption:
    points = []
    for leg in route["legs"]:
        for point in leg["points"]:
            points.append((point["latitude"], point["longitude"]))

    summary = route["summary"]
    totalSeconds = summary["travelTimeInSeconds"]

    # every instruction says where it is on the route and the time to get there,
    # so the stretch between two instructions is one step with its own duration
    steps = []
    prevIndex, prevSeconds = 0, 0
    for instruction in route.get("guidance", {}).get("instructions", []):
        index = instruction["pointIndex"]
        seconds = instruction["travelTimeInSeconds"]
        if index > prevIndex:
            steps.append(Step(prevIndex, index, max(seconds - prevSeconds, 0)))
            prevIndex, prevSeconds = index, seconds

    lastIndex = len(points) - 1
    if prevIndex < lastIndex:
        steps.append(Step(prevIndex, lastIndex, max(totalSeconds - prevSeconds, 0)))

    return RouteOption(
        routeId=routeId,
        points=points,
        steps=steps,
        totalMiles=summary["lengthInMeters"] / METERS_PER_MILE,
        totalSeconds=totalSeconds,
    )


def routesCacheKey(
    origin: Point, destination: Point, departure: datetime | None, loadLb: float
) -> str:
    # traffic changes by the hour, so departures in the same hour share routes
    departureKey = departure.astimezone(UTC).strftime("%Y-%m-%dT%H") if departure else "now"
    return (
        f"tomtom:routes:{origin[0]:.5f},{origin[1]:.5f}:{destination[0]:.5f},{destination[1]:.5f}"
        f":{departureKey}:{grossWeightKg(loadLb)}"
    )


def getRouteOptions(
    origin: Point, destination: Point, departure: datetime | None, loadLb: float
) -> list[RouteOption]:
    key = routesCacheKey(origin, destination, departure, loadLb)
    cached = cache.get(key)
    if cached is not None:
        return cached

    params: dict = {
        "key": getApiKey(),
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "vehicleWeight": grossWeightKg(loadLb),
        "routeType": "fastest",
        "traffic": "true",
        "maxAlternatives": len(ROUTE_IDS) - 1,
        "alternativeType": "anyRoute",
        "instructionsType": "coded",
    }
    if departure is not None:
        params["departAt"] = departure.astimezone(UTC).isoformat(timespec="seconds")

    locations = f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}"
    response = httpx.get(
        f"{TOMTOM_ROUTE_URL}/{locations}/json", params=params, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise readError(response)

    found = response.json().get("routes", [])
    if not found:
        raise TomTomError(response.status_code, "no route found")

    routes = []
    for i in range(min(len(found), len(ROUTE_IDS))):
        routes.append(parseRoute(found[i], ROUTE_IDS[i]))

    cache.set(key, routes, ROUTES_CACHE_SECONDS)
    return routes
