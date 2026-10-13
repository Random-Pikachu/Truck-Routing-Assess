import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from math import cos, pi, radians

import pytest

from routing.checkpoints import (
    EARTH_RADIUS,
    Checkpoint,
    Point,
    Step,
    checkpointGenerator,
    cumulativeDistance,
    haversine,
    pointAtMile,
    secondsSinceDeparture,
)

MILES_PER_DEGREE = EARTH_RADIUS * pi / 180
DEPARTURE = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)


def northRoute(miles: list[float]) -> list[Point]:
    """Points due north along longitude 0, placed at the given road miles."""
    return [(mile / MILES_PER_DEGREE, 0.0) for mile in miles]


def isNonDecreasing(values: list[float]) -> bool:
    return all(a <= b for a, b in pairwise(values))


# The dry-run route used throughout development: a city stretch (20 mph),
# an interstate (60 mph) and a state road (30 mph).
DRY_RUN_MILES = [0, 1, 2, 22, 52, 62, 67, 72]
DRY_RUN_STEPS = [Step(0, 2, 360), Step(2, 5, 3600), Step(5, 7, 1200)]
DRY_RUN_SECONDS = [0, 180, 360, 1560, 3360, 3960, 4560, 5160]


# --- haversine ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expectedMiles"),
    [
        pytest.param((0, 0), (1, 0), 69.094, id="1 deg latitude"),
        pytest.param((0, 0), (0, 1), 69.094, id="1 deg longitude at equator"),
        pytest.param((60, 0), (60, 1), 34.547, id="1 deg longitude at 60N shrinks"),
        pytest.param((40.7128, -74.0060), (34.0522, -118.2437), 2445.587, id="New York to LA"),
        pytest.param((0, 179.5), (0, -179.5), 69.094, id="across the 180 meridian"),
        pytest.param((89.9, 0), (89.9, 180), 13.819, id="over the north pole"),
        pytest.param((12.34, 56.78), (12.34, 56.78), 0.0, id="same point"),
    ],
)
def testHaversineKnownDistances(a: Point, b: Point, expectedMiles: float) -> None:
    assert haversine(a, b) == pytest.approx(expectedMiles, abs=0.01)


def testHaversineIsSymmetric() -> None:
    nyc, la = (40.7128, -74.0060), (34.0522, -118.2437)
    assert haversine(nyc, la) == pytest.approx(haversine(la, nyc))


# --- cumulativeDistance -------------------------------------------------------


def testCumulativeDistanceIsARunningTotal() -> None:
    points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    expected = [0, 69.094, 138.188, 207.283]
    assert cumulativeDistance(points) == pytest.approx(expected, abs=0.01)


def testCumulativeDistanceHasOneValuePerPoint() -> None:
    points = northRoute([0, 3, 9, 20, 41])
    distances = cumulativeDistance(points)
    assert len(distances) == len(points)
    assert distances[0] == 0.0
    assert isNonDecreasing(distances)


def testCumulativeDistanceFollowsTheRoadNotAStraightLine() -> None:
    """North 10 mi, east 10 mi, south 10 mi: driven 30 mi, though only 10 mi from the start."""
    up = 10 / MILES_PER_DEGREE
    east = 10 / (MILES_PER_DEGREE * cos(radians(up)))
    points = [(0.0, 0.0), (up, 0.0), (up, east), (0.0, east)]
    distances = cumulativeDistance(points)
    assert distances == pytest.approx([0, 10, 20, 30], abs=0.05)
    assert distances[-1] > haversine(points[0], points[-1]) * 2.9


def testCumulativeDistanceRepeatsValueForDuplicatePoint() -> None:
    distances = cumulativeDistance([(0, 0), (1, 0), (1, 0), (2, 0)])
    assert distances[1] == distances[2]
    assert distances == pytest.approx([0, 69.094, 69.094, 138.188], abs=0.01)


def testCumulativeDistanceSinglePoint() -> None:
    assert cumulativeDistance([(5, 5)]) == [0.0]


def testCumulativeDistanceRejectsEmptyRoute() -> None:
    with pytest.raises(ValueError):
        cumulativeDistance([])


# --- secondsSinceDeparture ----------------------------------------------------


def testSecondsMatchesDryRun() -> None:
    assert secondsSinceDeparture(DRY_RUN_MILES, DRY_RUN_STEPS) == pytest.approx(DRY_RUN_SECONDS)


def testSecondsUsesEachStepsOwnSpeed() -> None:
    """Two equal 10-mile steps, fast then slow: halfway is reached after the fast step only.

    A single average speed would put the halfway point at 1200 s instead of 600 s.
    """
    seconds = secondsSinceDeparture([0, 10, 20], [Step(0, 1, 600), Step(1, 2, 1800)])
    assert seconds == pytest.approx([0, 600, 2400])


def testSecondsSpreadsTimeInProportionToDistanceInsideAStep() -> None:
    seconds = secondsSinceDeparture([0, 1, 5, 10], [Step(0, 3, 1000)])
    assert seconds == pytest.approx([0, 100, 500, 1000])


def testSecondsSharedBoundaryPointIsNotDoubled() -> None:
    seconds = secondsSinceDeparture([0, 10, 30, 60], [Step(0, 2, 1800), Step(2, 3, 3600)])
    assert len(seconds) == 4
    assert seconds == pytest.approx([0, 600, 1800, 5400])


def testSecondsHandlesZeroLengthArriveStep() -> None:
    steps = [*DRY_RUN_STEPS, Step(7, 7, 0)]
    assert secondsSinceDeparture(DRY_RUN_MILES, steps) == pytest.approx(DRY_RUN_SECONDS)


def testSecondsZeroLengthStepMidRouteKeepsArrivalTime() -> None:
    """A wait at one spot (e.g. a ferry): its start point keeps the arrival time."""
    steps = [Step(0, 1, 100), Step(1, 2, 50), Step(2, 3, 80)]
    assert secondsSinceDeparture([0, 5, 5, 9], steps) == pytest.approx([0, 100, 150, 230])


def testSecondsTotalsAndShape() -> None:
    seconds = secondsSinceDeparture(DRY_RUN_MILES, DRY_RUN_STEPS)
    assert len(seconds) == len(DRY_RUN_MILES)
    assert seconds[0] == 0
    assert seconds[-1] == pytest.approx(sum(step.durationSeconds for step in DRY_RUN_STEPS))
    assert isNonDecreasing(seconds)


def testSecondsDoesNotModifyInputs() -> None:
    distances = list(DRY_RUN_MILES)
    steps = list(DRY_RUN_STEPS)
    secondsSinceDeparture(distances, steps)
    assert distances == DRY_RUN_MILES
    assert steps == DRY_RUN_STEPS


def testSecondsSinglePointRoute() -> None:
    assert secondsSinceDeparture([0.0], [Step(0, 0, 0)]) == [0.0]


# --- pointAtMile --------------------------------------------------------------

# Synthetic geometry: point i sits at lon -100 + 0.1 * i; distances are the dry run's.
SLIDE_POINTS = [(40.0, -100 + 0.1 * i) for i in range(8)]


@pytest.mark.parametrize(
    ("mile", "expectedSeconds"),
    [
        pytest.param(0, 0, id="origin"),
        pytest.param(25, 1740, id="between points 3 and 4"),
        pytest.param(22, 1560, id="exactly on a point"),
        pytest.param(57, 3660, id="halfway between 52 and 62"),
        pytest.param(72, 5160, id="destination"),
    ],
)
def testPointAtMileSeconds(mile: float, expectedSeconds: float) -> None:
    _, _, elapsed = pointAtMile(mile, SLIDE_POINTS, DRY_RUN_MILES, DRY_RUN_SECONDS)
    assert elapsed == pytest.approx(expectedSeconds)


def testPointAtMileInterpolatesPosition() -> None:
    """Mile 25 is 10% of the way from point 3 (lon -99.7) to point 4 (lon -99.6)."""
    lat, lon, _ = pointAtMile(25, SLIDE_POINTS, DRY_RUN_MILES, DRY_RUN_SECONDS)
    assert lat == pytest.approx(40.0)
    assert lon == pytest.approx(-99.69)


def testPointAtMileZeroIsTheOriginNotTheDestination() -> None:
    lat, lon, elapsed = pointAtMile(0, SLIDE_POINTS, DRY_RUN_MILES, DRY_RUN_SECONDS)
    assert (lat, lon) == pytest.approx(SLIDE_POINTS[0])
    assert elapsed == 0


def testPointAtMileAtTheEndIsTheDestination() -> None:
    lat, lon, elapsed = pointAtMile(72, SLIDE_POINTS, DRY_RUN_MILES, DRY_RUN_SECONDS)
    assert (lat, lon) == SLIDE_POINTS[-1]
    assert elapsed == DRY_RUN_SECONDS[-1]


@pytest.mark.parametrize("mile", [-1, -0.001, 72.001, 80])
def testPointAtMileRejectsMilesOutsideTheRoute(mile: float) -> None:
    with pytest.raises(ValueError):
        pointAtMile(mile, SLIDE_POINTS, DRY_RUN_MILES, DRY_RUN_SECONDS)


@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def testPointAtMileAroundDuplicatePointsDoesNotDivideByZero(offset: float) -> None:
    points = [(0, 0), (1, 0), (1, 0), (2, 0)]
    distances = cumulativeDistance(points)
    seconds = secondsSinceDeparture(distances, [Step(0, 3, 300)])
    lat, _, elapsed = pointAtMile(distances[1] + offset, points, distances, seconds)
    assert lat == pytest.approx(1.0, abs=0.001)
    assert elapsed == pytest.approx(150, abs=0.1)


def testPointAtMileSinglePointRoute() -> None:
    assert pointAtMile(0, [(5.0, 5.0)], [0.0], [0.0]) == (5.0, 5.0, 0.0)


# --- checkpointGenerator ------------------------------------------------------


def dryRunCheckpoints(interval: float, departure: datetime = DEPARTURE) -> list[Checkpoint]:
    return checkpointGenerator(northRoute(DRY_RUN_MILES), DRY_RUN_STEPS, departure, interval)


def testGeneratorReturnsAListOfCheckpoints() -> None:
    checkpoints = dryRunCheckpoints(25)
    assert isinstance(checkpoints, list)
    assert all(isinstance(cp, Checkpoint) for cp in checkpoints)


def testGeneratorMatchesDryRun() -> None:
    checkpoints = dryRunCheckpoints(25)
    assert [cp.mile for cp in checkpoints] == pytest.approx([0, 25, 50, 72])
    assert [cp.eta.strftime("%H:%M") for cp in checkpoints] == ["08:00", "08:29", "08:54", "09:26"]


@pytest.mark.parametrize(
    ("interval", "expectedMiles"),
    [
        pytest.param(10, [0, 10, 20, 30, 40, 50, 60, 70, 72], id="every 10 miles"),
        pytest.param(25, [0, 25, 50, 72], id="every 25 miles"),
        pytest.param(50, [0, 50, 72], id="every 50 miles"),
    ],
)
def testGeneratorMileMarks(interval: float, expectedMiles: list[float]) -> None:
    assert [cp.mile for cp in dryRunCheckpoints(interval)] == pytest.approx(expectedMiles)


def testGeneratorRouteShorterThanIntervalGivesOriginAndDestination() -> None:
    checkpoints = checkpointGenerator(northRoute([0, 10, 22]), [Step(0, 2, 1000)], DEPARTURE, 50)
    assert [cp.mile for cp in checkpoints] == pytest.approx([0, 22])


def testGeneratorExactMultipleHasNoDuplicateEnd() -> None:
    points = [(0.0, 0.0), (50 / MILES_PER_DEGREE, 0.0)]
    checkpoints = checkpointGenerator(points, [Step(0, 1, 3000)], DEPARTURE, 25)
    assert [cp.mile for cp in checkpoints] == pytest.approx([0, 25, 50])


@pytest.mark.xfail(strict=True, reason="end-of-route tolerance not implemented yet")
def testGeneratorNearlyExactMultipleHasNoNearDuplicateEnd() -> None:
    """A 50.004-mile route at 25 should not get checkpoints at both 50 and 50.004."""
    checkpoints = checkpointGenerator(northRoute([0, 50.004]), [Step(0, 1, 3000)], DEPARTURE, 25)
    assert [cp.mile for cp in checkpoints] == pytest.approx([0, 25, 50.004])


def testGeneratorSinglePointRoute() -> None:
    checkpoints = checkpointGenerator([(5.0, 5.0)], [Step(0, 0, 0)], DEPARTURE, 25)
    assert len(checkpoints) == 1
    assert checkpoints[0].eta == DEPARTURE


def testGeneratorFirstCheckpointIsTheOriginAtDeparture() -> None:
    points = northRoute(DRY_RUN_MILES)
    first = checkpointGenerator(points, DRY_RUN_STEPS, DEPARTURE, 25)[0]
    assert first.mile == 0
    assert (first.lat, first.lon) == pytest.approx(points[0])
    assert first.secondsFromStart == 0
    assert first.eta == DEPARTURE


def testGeneratorLastCheckpointIsTheDestination() -> None:
    points = northRoute(DRY_RUN_MILES)
    last = checkpointGenerator(points, DRY_RUN_STEPS, DEPARTURE, 25)[-1]
    assert last.mile == pytest.approx(72)
    assert (last.lat, last.lon) == points[-1]
    assert last.secondsFromStart == pytest.approx(5160)
    assert last.eta == DEPARTURE + timedelta(seconds=5160)


def testGeneratorEtaMatchesSecondsFromStart() -> None:
    for cp in dryRunCheckpoints(10):
        assert cp.eta - DEPARTURE == timedelta(seconds=cp.secondsFromStart)


def testGeneratorCheckpointsAreInOrder() -> None:
    checkpoints = dryRunCheckpoints(10)
    miles = [cp.mile for cp in checkpoints]
    assert all(a < b for a, b in pairwise(miles))
    assert isNonDecreasing([cp.secondsFromStart for cp in checkpoints])


def testGeneratorKeepsTheDeparturesTimezone() -> None:
    """13:30 IST is 08:00 UTC: same instants, shown in the caller's timezone."""
    ist = timezone(timedelta(hours=5, minutes=30))
    checkpoints = dryRunCheckpoints(25, departure=datetime(2026, 10, 14, 13, 30, tzinfo=ist))
    assert checkpoints[1].eta == DEPARTURE + timedelta(seconds=1740)
    assert checkpoints[1].eta.utcoffset() == timedelta(hours=5, minutes=30)


@pytest.mark.parametrize("interval", [0, 5, 15, 100, -25])
def testGeneratorRejectsUnsupportedIntervals(interval: float) -> None:
    with pytest.raises(ValueError):
        dryRunCheckpoints(interval)


def testGeneratorRejectsNaiveDeparture() -> None:
    with pytest.raises(ValueError):
        dryRunCheckpoints(25, departure=datetime(2026, 10, 14, 8, 0))


def testGeneratorRejectsEmptyRoute() -> None:
    with pytest.raises(ValueError):
        checkpointGenerator([], [], DEPARTURE, 25)


# --- data classes -------------------------------------------------------------


def testStepAndCheckpointAreImmutable() -> None:
    step = Step(0, 2, 360)
    checkpoint = Checkpoint(0.0, 40.0, -100.0, 0.0, DEPARTURE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.durationSeconds = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        checkpoint.eta = DEPARTURE + timedelta(hours=1)  # type: ignore[misc]
