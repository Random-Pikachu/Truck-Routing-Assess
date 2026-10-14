import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
from django.core.cache import cache
from dotenv import load_dotenv

from routing.checkpoints import Point, Step
from routing.ors import METERS_PER_MILE, ROUTE_IDS, RouteOption, viaPoints
from routing.similarity import isSameRoad

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOMTOM_ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute"
REQUEST_TIMEOUT_SECONDS = 30
LB_PER_KG = 2.20462

# TomTom wants the gross vehicle weight but the brief only gives the load,
# so a typical empty tractor-trailer is added on top of it
EMPTY_TRUCK_LB = 35000

# travel times include traffic, so they go stale faster than ORS routes
ROUTES_CACHE_SECONDS = 60 * 60

# when TomTom finds fewer than 3 different roads, force detours through points
# this far to the side of the midpoint (share of the trip), nearest first
DETOUR_FRACTIONS = [0.25, 0.5]


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


def requestRoutes(
    locations: list[Point], departure: datetime | None, loadLb: float, alternatives: int
) -> list[dict]:
    params: dict = {
        "key": getApiKey(),
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "vehicleWeight": grossWeightKg(loadLb),
        "routeType": "fastest",
        "traffic": "true",
        "instructionsType": "coded",
    }
    if alternatives > 0:
        params["maxAlternatives"] = alternatives
        params["alternativeType"] = "anyRoute"
    if departure is not None:
        params["departAt"] = departure.astimezone(UTC).isoformat(timespec="seconds")

    path = []
    for lat, lon in locations:
        path.append(f"{lat},{lon}")
    response = httpx.get(
        f"{TOMTOM_ROUTE_URL}/{':'.join(path)}/json", params=params, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise readError(response)

    found = response.json().get("routes", [])
    if not found:
        raise TomTomError(response.status_code, "no route found")
    return found


def requestDetour(
    origin: Point, via: Point, destination: Point, departure: datetime | None, loadLb: float
) -> RouteOption | None:
    try:
        found = requestRoutes([origin, via, destination], departure, loadLb, alternatives=0)
        return parseRoute(found[0], "")
    except (TomTomError, httpx.HTTPError, KeyError):
        # a via point can land somewhere with no road (a lake, a park), that detour is just skipped
        return None


def addIfNew(routes: list[RouteOption], candidate: RouteOption) -> None:
    others = []
    for route in routes:
        others.append(route.points)
    if len(routes) < len(ROUTE_IDS) and not isSameRoad(candidate.points, others):
        routes.append(replace(candidate, routeId=ROUTE_IDS[len(routes)]))


def getRouteOptions(
    origin: Point, destination: Point, departure: datetime | None, loadLb: float
) -> list[RouteOption]:
    key = routesCacheKey(origin, destination, departure, loadLb)
    cached = cache.get(key)
    if cached is not None:
        return cached

    routes: list[RouteOption] = []
    found = requestRoutes([origin, destination], departure, loadLb, len(ROUTE_IDS) - 1)
    for feature in found:
        addIfNew(routes, parseRoute(feature, ""))

    if len(routes) < len(ROUTE_IDS):
        vias = []
        for fraction in DETOUR_FRACTIONS:
            left, right = viaPoints(origin, destination, fraction)
            vias.append(left)
            vias.append(right)

        # all detours at once, then taken in order so the closest ones win
        with ThreadPoolExecutor(max_workers=len(vias)) as pool:
            detours = list(
                pool.map(
                    lambda via: requestDetour(origin, via, destination, departure, loadLb), vias
                )
            )
        for detour in detours:
            if detour is not None:
                addIfNew(routes, detour)

    cache.set(key, routes, ROUTES_CACHE_SECONDS)
    return routes
