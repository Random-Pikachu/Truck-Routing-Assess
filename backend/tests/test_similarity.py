import pytest

from routing.checkpoints import Point, Step, haversine
from routing.ors import RouteOption, isDuplicate
from routing.similarity import SAMPLE_EVERY_MILES, cellOf, isSameRoad, overlapShare, resample


def line(start: Point, end: Point, count: int = 50) -> list[Point]:
    points = []
    for i in range(count + 1):
        fraction = i / count
        lat = start[0] + fraction * (end[0] - start[0])
        lon = start[1] + fraction * (end[1] - start[1])
        points.append((lat, lon))
    return points


# a ~138 mile road going north along -90
SOUTH = (38.0, -90.0)
NORTH = (40.0, -90.0)
MAIN = line(SOUTH, NORTH)


def testResampleIsEvenlySpaced() -> None:
    samples = resample(MAIN)
    for i in range(1, len(samples)):
        assert haversine(samples[i - 1], samples[i]) == pytest.approx(SAMPLE_EVERY_MILES, rel=1e-3)
    assert samples[0] == SOUTH


def testResampleIgnoresHowManyVerticesARoadHas() -> None:
    assert len(resample(line(SOUTH, NORTH, 5))) == len(resample(line(SOUTH, NORTH, 500)))


def testResampleHandlesRepeatedPoints() -> None:
    samples = resample([SOUTH, SOUTH, NORTH, NORTH])
    assert len(samples) == len(resample([SOUTH, NORTH]))


def testResampleOfOnePointIsThatPoint() -> None:
    assert resample([SOUTH]) == [SOUTH]


def testSameRoadOverlapsFully() -> None:
    assert overlapShare(MAIN, MAIN) == 1.0


def testRoadHalfAMileAwayStillCounts() -> None:
    nearby = line((38.0, -90.009), (40.0, -90.009))  # ~0.5 mi west, in the next grid cell
    assert cellOf(nearby[0]) != cellOf(MAIN[0])
    assert overlapShare(nearby, MAIN) == 1.0


def testParallelRoadFarAwayDoesNotOverlap() -> None:
    parallel = line((38.0, -89.8), (40.0, -89.8))  # ~11 mi east
    assert overlapShare(parallel, MAIN) == 0.0


def testOverlapIsMeasuredByDistance() -> None:
    # first half on the main road, second half on a road 11 mi east
    split = line(SOUTH, (39.0, -90.0)) + line((39.0, -89.8), (40.0, -89.8))
    assert overlapShare(split, MAIN) == pytest.approx(0.5, abs=0.03)


def testSmallDeviationIsTheSameRoad() -> None:
    # leaves the main road for ~7 miles in the middle, like the Casper -> Denver east detour
    deviation = [*line(SOUTH, (38.95, -90.0)), (39.0, -89.9), *line((39.05, -90.0), NORTH)]
    assert overlapShare(deviation, MAIN) > 0.85
    assert isSameRoad(deviation, [MAIN])


def testRouteWithAnOutAndBackSpurIsTheSameRoad() -> None:
    """A via point off to the side can make a route drive all of the direct one plus a spur."""
    spur = line(SOUTH, (39.0, -90.0)) + line((39.0, -90.0), (39.0, -89.0))
    spur += line((39.0, -89.0), (39.0, -90.0)) + line((39.0, -90.0), NORTH)
    assert overlapShare(spur, MAIN) < 0.85  # most of its miles are the spur
    assert overlapShare(MAIN, spur) == 1.0  # but the whole direct road is inside it
    assert isSameRoad(spur, [MAIN])


def testDifferentRoadIsNotTheSameRoad() -> None:
    west = line(SOUTH, (39.0, -91.0)) + line((39.0, -91.0), NORTH)
    assert not isSameRoad(west, [MAIN])


def testIsSameRoadChecksEveryRoute() -> None:
    west = line(SOUTH, (39.0, -91.0)) + line((39.0, -91.0), NORTH)
    assert isSameRoad(MAIN, [west, MAIN])


def testNothingToCompareWithIsNotASameRoad() -> None:
    assert not isSameRoad(MAIN, [])


# ---------- ORS detours use it too ----------


def option(points: list[Point], miles: float, seconds: float) -> RouteOption:
    return RouteOption("A", points, [Step(0, len(points) - 1, seconds)], miles, seconds)


def testOrsDetourThatRejoinsTheDirectRoadIsADuplicate() -> None:
    direct = option(MAIN, 138, 9000)
    deviation = [*line(SOUTH, (38.95, -90.0)), (39.0, -89.9), *line((39.05, -90.0), NORTH)]
    # 4 miles and 16 minutes apart, the old totals check alone let it through
    assert isDuplicate(option(deviation, 142, 9960), [direct])


def testOrsDetourOnAnotherRoadIsKept() -> None:
    direct = option(MAIN, 138, 9000)
    west = line(SOUTH, (39.0, -91.0)) + line((39.0, -91.0), NORTH)
    assert not isDuplicate(option(west, 180, 12000), [direct])


def testOrsSameTotalsAreStillADuplicate() -> None:
    direct = option(MAIN, 138, 9000)
    west = line(SOUTH, (39.0, -91.0)) + line((39.0, -91.0), NORTH)
    assert isDuplicate(option(west, 138.2, 9030), [direct])
