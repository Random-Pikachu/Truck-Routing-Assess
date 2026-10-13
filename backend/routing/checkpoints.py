from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt

Point = tuple[float, float]

EARTH_RADIUS = 3958.8


@dataclass(frozen=True)
class Step:
    startIndex: int
    endIndex: int
    durationSeconds: float


@dataclass(frozen=True)
class Checkpoint:
    mile: float
    lat: float
    lon: float
    secondsFromStart: float
    eta: datetime


def haversine(p0: Point, p1: Point) -> float:
    lat0, lon0 = map(radians, p0)
    lat1, lon1 = map(radians, p1)

    dlat, dlon = lat1 - lat0, lon1 - lon0
    a = sin(dlat / 2) ** 2 + cos(lat0) * cos(lat1) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = EARTH_RADIUS * c
    return distance


def cumulativeDistance(points: list[Point]) -> list[float]:
    if not points:
        raise ValueError("Points can't be empty")
    distances = [0.0]
    for i in range(1, len(points)):
        prevPoint = points[i - 1]
        currPoint = points[i]
        distances.append(distances[i - 1] + haversine(prevPoint, currPoint))

    return distances


def secondsSinceDeparture(distances: list[float], steps: list[Step]) -> list[float]:
    seconds = [0.0] * len(distances)
    clock = 0.0

    for step in steps:
        startIdx, endIdx, duration = step.startIndex, step.endIndex, step.durationSeconds
        startDistance = distances[startIdx]
        stepLength = distances[endIdx] - startDistance

        for i in range(startIdx, endIdx + 1):
            if stepLength == 0:
                fraction = 0.0 if i == startIdx else 1.0
            else:
                fraction = (distances[i] - startDistance) / stepLength
            seconds[i] = clock + fraction * duration

        clock += duration

    return seconds


def pointAtMile(
    mile: float, points: list[Point], distances: list[float], seconds: list[float]
) -> tuple[float, float, float]:
    total = distances[-1]
    if mile < 0 or mile > total:
        raise ValueError(f"Mile {mile} is outside the route (0 to {total:.2f})")

    if mile == total:
        lat, lon = points[-1]
        return lat, lon, seconds[-1]

    hi = bisect_right(distances, mile)
    lo = hi - 1
    fraction = (mile - distances[lo]) / (distances[hi] - distances[lo])

    (latLo, lonLo), (latHi, lonHi) = points[lo], points[hi]
    lat = latLo + fraction * (latHi - latLo)
    lon = lonLo + fraction * (lonHi - lonLo)
    elapsed = seconds[lo] + fraction * (seconds[hi] - seconds[lo])

    return lat, lon, elapsed


def checkpointGenerator(
    points: list[Point], steps: list[Step], departure: datetime, interval: float
) -> list[Checkpoint]:
    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be a timezone-aware datetime")

    if interval not in [10, 25, 50]:
        raise ValueError(f"Interval must be 10, 25 or 50 miles, got {interval}")
    distances = cumulativeDistance(points)
    seconds = secondsSinceDeparture(distances, steps)
    total = distances[-1]
    marks = [0.0]  # checkpoint marks
    mark = 0.0
    checkpoints = []
    while mark < total:
        mark += interval
        if mark > total:
            mark = total
        marks.append(mark)

    for mark in marks:
        lat, lon, elapsed = pointAtMile(mark, points, distances, seconds)
        eta = departure + timedelta(seconds=elapsed)
        cp = Checkpoint(mile=mark, lat=lat, lon=lon, secondsFromStart=elapsed, eta=eta)
        checkpoints.append(cp)

    return checkpoints
