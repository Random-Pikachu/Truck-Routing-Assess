import math
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

from routing.checkpoints import Point, Step, haversine

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ORS_BASE_URL = "https://api.openrouteservice.org"
METERS_PER_MILE = 1609.344
REQUEST_TIMEOUT_SECONDS = 30
ROUTE_IDS = ["A", "B", "C"]

# ORS alternative routes only work for routes under 100 km (error 2004 otherwise).
# 40 straight-line miles keeps the road distance safely below that.
SHORT_TRIP_MAX_MILES = 40
ALTERNATIVES_LIMIT_ERROR = 2004
VIA_OFFSET_FRACTION = 0.25


@dataclass(frozen=True)
class RouteOption:
    routeId: str
    points: list[Point]
    steps: list[Step]
    totalMiles: float
    totalSeconds: float


class OrsError(RuntimeError):
    def __init__(self, code: int | None, message: str):
        super().__init__(f"ORS error {code}: {message}")
        self.code = code


def getApiKey() -> str:
    key = os.environ.get("ORS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ORS_API_KEY is not set, add it to backend/.env")
    return key


def readError(response: httpx.Response) -> OrsError:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return OrsError(response.status_code, response.text[:200])

    if isinstance(error, dict):
        return OrsError(error.get("code", response.status_code), error.get("message", ""))
    return OrsError(response.status_code, str(error))


def geocode(text: str) -> tuple[Point, str]:
    response = httpx.get(
        f"{ORS_BASE_URL}/geocode/search",
        params={"api_key": getApiKey(), "text": text, "size": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise readError(response)

    features = response.json()["features"]
    if not features:
        raise ValueError(f"No location found for '{text}'")

    lon, lat = features[0]["geometry"]["coordinates"][:2]
    return (lat, lon), features[0]["properties"]["label"]


def requestDirections(coordinates: list[Point], alternatives: bool) -> list[dict]:
    lonLatCoordinates = []
    for lat, lon in coordinates:
        lonLatCoordinates.append([lon, lat])

    # radius -1 lets ORS snap a via-point to the nearest road however far it is
    body: dict = {"coordinates": lonLatCoordinates, "radiuses": [-1] * len(coordinates)}
    if alternatives:
        body["alternative_routes"] = {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.6}

    response = httpx.post(
        f"{ORS_BASE_URL}/v2/directions/driving-hgv/geojson",
        json=body,
        headers={"Authorization": getApiKey()},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise readError(response)

    return response.json()["features"]


def parseRoute(feature: dict, routeId: str) -> RouteOption:
    points = []
    for coordinate in feature["geometry"]["coordinates"]:
        points.append((coordinate[1], coordinate[0]))

    steps = []
    for segment in feature["properties"]["segments"]:
        for step in segment["steps"]:
            startIndex, endIndex = step["way_points"]
            steps.append(Step(startIndex, endIndex, step["duration"]))

    summary = feature["properties"]["summary"]
    return RouteOption(
        routeId=routeId,
        points=points,
        steps=steps,
        totalMiles=summary.get("distance", 0.0) / METERS_PER_MILE,
        totalSeconds=summary.get("duration", 0.0),
    )


def viaPoints(origin: Point, destination: Point) -> tuple[Point, Point]:
    midLat = (origin[0] + destination[0]) / 2
    midLon = (origin[1] + destination[1]) / 2
    dLat = destination[0] - origin[0]
    dLon = destination[1] - origin[1]
    length = math.hypot(dLat, dLon)
    if length == 0:
        raise ValueError("Origin and destination are the same point")

    # unit vector perpendicular to the origin -> destination line
    perpLat, perpLon = -dLon / length, dLat / length
    offset = VIA_OFFSET_FRACTION * length

    left = (midLat + perpLat * offset, midLon + perpLon * offset)
    right = (midLat - perpLat * offset, midLon - perpLon * offset)
    return left, right


def isDuplicate(candidate: RouteOption, routes: list[RouteOption]) -> bool:
    for route in routes:
        sameMiles = abs(route.totalMiles - candidate.totalMiles) < 0.5
        sameTime = abs(route.totalSeconds - candidate.totalSeconds) < 60
        if sameMiles and sameTime:
            return True
    return False


def getRouteOptions(origin: Point, destination: Point) -> list[RouteOption]:
    routes = []

    if haversine(origin, destination) <= SHORT_TRIP_MAX_MILES:
        try:
            features = requestDirections([origin, destination], alternatives=True)
            for i in range(min(len(features), len(ROUTE_IDS))):
                routes.append(parseRoute(features[i], ROUTE_IDS[i]))
        except OrsError as error:
            if error.code != ALTERNATIVES_LIMIT_ERROR:
                raise

    if not routes:
        direct = requestDirections([origin, destination], alternatives=False)[0]
        routes.append(parseRoute(direct, ROUTE_IDS[0]))

    if len(routes) < len(ROUTE_IDS):
        for via in viaPoints(origin, destination):
            if len(routes) == len(ROUTE_IDS):
                break
            try:
                feature = requestDirections([origin, via, destination], alternatives=False)[0]
            except OrsError:
                continue
            candidate = parseRoute(feature, ROUTE_IDS[len(routes)])
            if not isDuplicate(candidate, routes):
                routes.append(candidate)

    return routes
