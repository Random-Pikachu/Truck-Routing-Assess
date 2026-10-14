from math import floor

from routing.checkpoints import Point, cumulativeDistance

SAMPLE_EVERY_MILES = 0.25
# ~0.7 mi cells, with the neighbouring cells a point counts as "on" a road within ~1 mi
CELL_DEGREES = 0.01
# a route that drives 85% of its miles on another one (either way round) is the same route
SAME_ROAD_SHARE = 0.85


def resample(points: list[Point], everyMiles: float = SAMPLE_EVERY_MILES) -> list[Point]:
    # evenly spaced, so a city stretch with lots of vertices doesn't outweigh a highway
    if len(points) < 2:
        return list(points)
    distances = cumulativeDistance(points)
    total = distances[-1]

    samples = []
    i = 0
    mark = 0.0
    while mark <= total:
        while i < len(points) - 2 and distances[i + 1] < mark:
            i += 1
        gap = distances[i + 1] - distances[i]
        fraction = 0.0 if gap == 0 else (mark - distances[i]) / gap
        lat = points[i][0] + fraction * (points[i + 1][0] - points[i][0])
        lon = points[i][1] + fraction * (points[i + 1][1] - points[i][1])
        samples.append((lat, lon))
        mark += everyMiles
    return samples


def cellOf(point: Point) -> tuple[int, int]:
    return floor(point[0] / CELL_DEGREES), floor(point[1] / CELL_DEGREES)


def roadCells(points: list[Point]) -> set[tuple[int, int]]:
    cells = set()
    for point in resample(points):
        cells.add(cellOf(point))
    return cells


def overlapShare(candidate: list[Point], other: list[Point]) -> float:
    """How much of `candidate` (by distance) runs along `other`, from 0 to 1."""
    samples = resample(candidate)
    if not samples:
        return 0.0
    cells = roadCells(other)

    near = 0
    for sample in samples:
        row, col = cellOf(sample)
        found = False
        for dRow in (-1, 0, 1):
            for dCol in (-1, 0, 1):
                if (row + dRow, col + dCol) in cells:
                    found = True
        if found:
            near += 1
    return near / len(samples)


def isSameRoad(candidate: list[Point], routes: list[list[Point]]) -> bool:
    for route in routes:
        # mostly on an existing route, or an existing route plus an out-and-back spur to a via point
        if overlapShare(candidate, route) >= SAME_ROAD_SHARE:
            return True
        if overlapShare(route, candidate) >= SAME_ROAD_SHARE:
            return True
    return False
