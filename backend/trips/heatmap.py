from dataclasses import dataclass
from datetime import UTC, datetime
from math import cos, hypot, pi, radians

from risk.engine import RiskLevel, classify
from routing import ors, provider
from routing.checkpoints import EARTH_RADIUS, Point, cumulativeDistance, haversine, pointAtMile
from weather import openmeteo
from weather.openmeteo import ONE_HOUR, HourlySeries, floorHour, gridKey, hourIndex

HEATMAP_HOURS = 48  # frames 0 .. 48, one per hour from now
CORRIDOR_STEP_MILES = 25
MAX_SAMPLES_PER_ROUTE = 30  # long trips get a wider step instead of more points
CORRIDOR_HALF_WIDTH_MILES = 20
HEATMAP_GRID_DEGREES = 0.25
SAME_PLACE_MILES = 0.5
MILES_PER_DEGREE = EARTH_RADIUS * pi / 180


@dataclass(frozen=True)
class Heatmap:
    startHour: datetime
    points: list[Point]
    risk: list[list[RiskLevel | None]]  # risk[hour][point], None where the forecast is missing


def heatmapGridKey(point: Point) -> Point:
    lat = round(round(point[0] / HEATMAP_GRID_DEGREES) * HEATMAP_GRID_DEGREES, 4)
    lon = round(round(point[1] / HEATMAP_GRID_DEGREES) * HEATMAP_GRID_DEGREES, 4)
    return lat, lon


def offsetPoint(center: Point, behind: Point, ahead: Point, miles: float) -> Point:
    # move `miles` sideways (left is positive) from the direction of travel
    milesPerLonDegree = MILES_PER_DEGREE * cos(radians(center[0]))
    north = (ahead[0] - behind[0]) * MILES_PER_DEGREE
    east = (ahead[1] - behind[1]) * milesPerLonDegree
    length = hypot(north, east)
    if miles == 0 or length == 0:
        return center

    leftNorth, leftEast = east / length, -north / length
    return (
        center[0] + leftNorth * miles / MILES_PER_DEGREE,
        center[1] + leftEast * miles / milesPerLonDegree,
    )


def corridorPoints(routes: list[list[Point]]) -> list[Point]:
    points = []
    seen = set()

    for routePoints in routes:
        distances = cumulativeDistance(routePoints)
        total = distances[-1]
        noSeconds = [0.0] * len(distances)
        step = max(CORRIDOR_STEP_MILES, total / MAX_SAMPLES_PER_ROUTE)

        marks = []
        mark = 0.0
        while mark < total:
            marks.append(mark)
            mark += step
        marks.append(total)

        for mark in marks:
            lat, lon, _ = pointAtMile(mark, routePoints, distances, noSeconds)
            behindLat, behindLon, _ = pointAtMile(
                max(mark - 1, 0), routePoints, distances, noSeconds
            )
            aheadLat, aheadLon, _ = pointAtMile(
                min(mark + 1, total), routePoints, distances, noSeconds
            )

            for sideways in [0, CORRIDOR_HALF_WIDTH_MILES, -CORRIDOR_HALF_WIDTH_MILES]:
                point = offsetPoint(
                    (lat, lon), (behindLat, behindLon), (aheadLat, aheadLon), sideways
                )
                key = heatmapGridKey(point)
                if key not in seen:
                    seen.add(key)
                    points.append(key)

    return points


def riskAt(series: HourlySeries | None, hour: datetime, loadLb: float) -> RiskLevel | None:
    # frame `hour` is the hour from `hour` to `hour + 1`: wind at its start,
    # rain and snow totalled over it (Open-Meteo labels that total with the hour's end)
    if series is None:
        return None
    windIndex = hourIndex(series, hour)
    precipIndex = hourIndex(series, hour + ONE_HOUR)
    if windIndex is None or precipIndex is None:
        return None

    wind = series.wind[windIndex]
    rain = series.rain[precipIndex]
    snow = series.snow[precipIndex]
    if wind is None or rain is None or snow is None:
        return None
    return classify(wind, rain, snow, loadLb)


def buildHeatmap(
    originText: str, destinationText: str, loadLb: float, now: datetime | None = None
) -> Heatmap:
    if loadLb < 0:
        raise ValueError("Load weight can't be negative")

    origin, _ = ors.geocode(originText)
    destination, _ = ors.geocode(destinationText)
    if haversine(origin, destination) < SAME_PLACE_MILES:
        raise ValueError("Origin and destination are the same place")

    routes = provider.getRouteOptions(origin, destination, None, loadLb)
    routePoints = []
    for route in routes:
        routePoints.append(route.points)
    points = corridorPoints(routePoints)

    startHour = floorHour(now or datetime.now(UTC))
    endHour = startHour + (HEATMAP_HOURS + 1) * ONE_HOUR  # the last frame needs the hour after it
    seriesByKey = openmeteo.fetchHourly(points, startHour, endHour)

    risk = []
    for h in range(HEATMAP_HOURS + 1):
        hour = startHour + h * ONE_HOUR
        row = []
        for point in points:
            row.append(riskAt(seriesByKey.get(gridKey(point)), hour, loadLb))
        risk.append(row)

    return Heatmap(startHour=startHour, points=points, risk=risk)
