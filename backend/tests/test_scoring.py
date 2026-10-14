from itertools import combinations, permutations

import pytest

from risk.engine import RiskLevel
from risk.scoring import (
    AVG_RISK_TOLERANCE,
    HIGH_MILES_TOLERANCE,
    SEVERE_MILES_TOLERANCE,
    RouteSummary,
    compareRoutes,
    decidingRule,
    formatDuration,
    generateRouteSummary,
    milesPerRisk,
    ownedMiles,
    rankRoutes,
    recommendRoute,
    toleranceChecker,
)

R = RiskLevel


def summary(
    routeId: str,
    severe: float = 0.0,
    high: float = 0.0,
    avgRisk: float = 0.0,
    hours: float = 5.0,
    drivable: bool = True,
) -> RouteSummary:
    """Hand-made RouteSummary for ranking tests; only the fields ranking reads matter."""
    miles = {level: 0.0 for level in RiskLevel}
    miles[R.SEVERE] = severe
    miles[R.HIGH] = high
    return RouteSummary(routeId, 300.0, hours * 3600, miles, avgRisk, drivable)


def ids(routes: list[RouteSummary]) -> list[str]:
    return [route.routeId for route in routes]


# The worked example from development:
#   A has 40 Severe miles; B and C tie on Severe and (within tolerance) High,
#   so C's lower average risk wins; D is fastest and safest but not drivable.
ROUTE_A = summary("A", severe=40, high=20, avgRisk=1.1, hours=5.0)
ROUTE_B = summary("B", severe=0, high=35.0, avgRisk=0.9, hours=5.5)
ROUTE_C = summary("C", severe=0, high=35.6, avgRisk=0.7, hours=5.2)
ROUTE_D = summary("D", severe=0, high=0, avgRisk=0.4, hours=4.8, drivable=False)


# --- toleranceChecker ---------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "y", "tolerance", "expected"),
    [
        pytest.param(35.0, 35.6, 1.0, 0, id="within tolerance, x smaller -> tie"),
        pytest.param(35.6, 35.0, 1.0, 0, id="within tolerance, x larger -> tie"),
        pytest.param(10.0, 11.0, 1.0, 0, id="difference exactly the tolerance -> tie"),
        pytest.param(10.0, 11.5, 1.0, -1, id="x clearly smaller -> x better"),
        pytest.param(11.5, 10.0, 1.0, 1, id="x clearly larger -> y better"),
        pytest.param(0.9, 0.7, 0.05, 1, id="average risk example"),
        pytest.param(5.0, 5.0, 0.0, 0, id="exact compare, equal"),
        pytest.param(5.0, 5.1, 0.0, -1, id="exact compare, smaller"),
    ],
)
def testToleranceChecker(x: float, y: float, tolerance: float, expected: int) -> None:
    assert toleranceChecker(x, y, tolerance) == expected


# --- ownedMiles ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("checkpointMiles", "totalMiles", "expected"),
    [
        pytest.param([0, 25, 50, 72], 72, [12.5, 25, 23.5, 11], id="docstring example"),
        pytest.param([0, 10, 20, 30], 30, [5, 10, 10, 5], id="even spacing"),
        pytest.param([0, 22], 22, [11, 11], id="two checkpoints split the route"),
        pytest.param([0], 15, [15], id="single checkpoint owns the whole route"),
        pytest.param([0], 0, [0], id="zero-length route"),
    ],
)
def testOwnedMiles(checkpointMiles: list[float], totalMiles: float, expected: list[float]) -> None:
    assert ownedMiles(checkpointMiles, totalMiles) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("checkpointMiles", "totalMiles"),
    [
        ([0, 25, 50, 72], 72),
        ([0, 10, 20, 30, 40, 50, 60, 70, 72], 72),
        ([0, 50, 100, 150, 187.3], 187.3),
        ([0, 25, 50, 50.004], 50.004),
    ],
)
def testOwnedMilesAlwaysSumToTheRouteLength(
    checkpointMiles: list[float], totalMiles: float
) -> None:
    owned = ownedMiles(checkpointMiles, totalMiles)
    assert len(owned) == len(checkpointMiles)
    assert sum(owned) == pytest.approx(totalMiles)
    assert all(miles >= 0 for miles in owned)


# --- milesPerRisk -------------------------------------------------------------


def testMilesPerRiskMatchesWorkedExample() -> None:
    milesByLevel, avgRisk = milesPerRisk([R.LOW, R.SEVERE, R.HIGH, R.LOW], [12.5, 25, 23.5, 11])
    assert milesByLevel[R.LOW] == pytest.approx(23.5)
    assert milesByLevel[R.HIGH] == pytest.approx(23.5)
    assert milesByLevel[R.SEVERE] == pytest.approx(25)
    assert avgRisk == pytest.approx(122 / 72)


def testMilesPerRiskAlwaysHasEveryLevel() -> None:
    milesByLevel, _ = milesPerRisk([R.LOW], [10.0])
    assert set(milesByLevel) == set(RiskLevel)
    assert milesByLevel[R.SEVERE] == 0.0
    assert milesByLevel[R.NO_TRAVEL] == 0.0


def testMilesPerRiskCountsNoTravelMiles() -> None:
    milesByLevel, avgRisk = milesPerRisk([R.LOW, R.NO_TRAVEL], [10.0, 10.0])
    assert milesByLevel[R.NO_TRAVEL] == pytest.approx(10)
    assert avgRisk == pytest.approx(2.0)


def testMilesPerRiskAverageIsWeightedByDistance() -> None:
    """A long LOW stretch outweighs a short SEVERE one."""
    _, avgRisk = milesPerRisk([R.LOW, R.SEVERE], [90.0, 10.0])
    assert avgRisk == pytest.approx(0.3)


def testMilesPerRiskZeroLengthRouteUsesPlainAverage() -> None:
    _, avgRisk = milesPerRisk([R.HIGH], [0.0])
    assert avgRisk == pytest.approx(2.0)


def testMilesPerRiskRejectsMismatchedLists() -> None:
    with pytest.raises(ValueError):
        milesPerRisk([R.LOW, R.HIGH], [10.0])


def testMilesPerRiskRejectsEmptyRoute() -> None:
    with pytest.raises(ValueError):
        milesPerRisk([], [])


# --- generateRouteSummary -----------------------------------------------------


def testGenerateRouteSummaryWorkedExample() -> None:
    result = generateRouteSummary("A", [0, 25, 50, 72], [R.LOW, R.SEVERE, R.HIGH, R.LOW], 72, 5160)
    assert result.routeId == "A"
    assert result.totalMiles == 72
    assert result.totalSeconds == 5160
    assert result.milesPerRiskLvl[R.SEVERE] == pytest.approx(25)
    assert result.milesPerRiskLvl[R.HIGH] == pytest.approx(23.5)
    assert result.avgRisk == pytest.approx(122 / 72)
    assert result.drivable is True


def testGenerateRouteSummaryNoTravelRouteIsSummarisedButNotDrivable() -> None:
    result = generateRouteSummary("D", [0, 25, 50], [R.LOW, R.NO_TRAVEL, R.LOW], 50, 3000)
    assert result.drivable is False
    assert result.milesPerRiskLvl[R.NO_TRAVEL] == pytest.approx(25)


def testGenerateRouteSummarySinglePointRoute() -> None:
    result = generateRouteSummary("S", [0], [R.HIGH], 0, 0)
    assert result.avgRisk == pytest.approx(2.0)
    assert result.drivable is True


# --- compareRoutes ------------------------------------------------------------


@pytest.mark.parametrize(
    ("better", "worse"),
    [
        pytest.param(summary("X"), summary("Y", drivable=False), id="drivable beats not drivable"),
        pytest.param(
            summary("X", severe=0, high=90, avgRisk=2.5, hours=9),
            summary("Y", severe=10, high=0, avgRisk=0.1, hours=1),
            id="severe miles outrank everything below",
        ),
        pytest.param(
            summary("X", high=5, avgRisk=2.5, hours=9),
            summary("Y", high=20, avgRisk=0.1, hours=1),
            id="high miles outrank average and time",
        ),
        pytest.param(
            summary("X", avgRisk=0.5, hours=9),
            summary("Y", avgRisk=0.9, hours=1),
            id="average risk outranks time",
        ),
        pytest.param(summary("X", hours=4), summary("Y", hours=5), id="time breaks a full tie"),
        pytest.param(
            summary("X", drivable=False, severe=0),
            summary("Y", drivable=False, severe=30),
            id="two undrivable routes still compared by the rules",
        ),
    ],
)
def testCompareRoutesRuleOrder(better: RouteSummary, worse: RouteSummary) -> None:
    assert compareRoutes(better, worse) == -1
    assert compareRoutes(worse, better) == 1


def testCompareRoutesTieWithinToleranceFallsThroughToNextRule() -> None:
    """B and C: Severe equal, High 0.6 apart (a tie), so average risk decides for C."""
    assert compareRoutes(ROUTE_C, ROUTE_B) == -1
    assert compareRoutes(ROUTE_B, ROUTE_C) == 1


@pytest.mark.parametrize(
    ("field", "tolerance"),
    [("severe", SEVERE_MILES_TOLERANCE), ("high", HIGH_MILES_TOLERANCE)],
)
def testCompareRoutesMileTolerancesAreInclusive(field: str, tolerance: float) -> None:
    """A difference of exactly the tolerance is a tie; just above it decides."""
    base = summary("X", avgRisk=0.9, **{field: 10.0})
    atTolerance = summary("Y", avgRisk=0.5, **{field: 10.0 + tolerance})
    beyond = summary("Z", avgRisk=0.5, **{field: 10.0 + tolerance + 0.01})
    assert compareRoutes(atTolerance, base) == -1  # tie on miles, lower avg risk wins
    assert compareRoutes(base, beyond) == -1  # miles now decide


def testCompareRoutesAverageRiskTolerance() -> None:
    a = summary("X", avgRisk=0.70, hours=6)
    b = summary("Y", avgRisk=0.70 + AVG_RISK_TOLERANCE / 2, hours=5)
    assert compareRoutes(b, a) == -1  # averages tie, so the faster route wins


def testCompareRoutesIdenticalRoutesTie() -> None:
    assert compareRoutes(summary("X"), summary("Y")) == 0


def testCompareRoutesIsConsistentBothWays() -> None:
    """compare(a, b) must always be the opposite of compare(b, a)."""
    for a, b in combinations([ROUTE_A, ROUTE_B, ROUTE_C, ROUTE_D], 2):
        assert compareRoutes(a, b) == -compareRoutes(b, a)


# --- rankRoutes ---------------------------------------------------------------


def testRankRoutesWorkedExample() -> None:
    assert ids(rankRoutes([ROUTE_A, ROUTE_B, ROUTE_C, ROUTE_D])) == ["C", "B", "A", "D"]


def testRankRoutesSameResultForEveryInputOrder() -> None:
    for order in permutations([ROUTE_A, ROUTE_B, ROUTE_C, ROUTE_D]):
        assert ids(rankRoutes(list(order))) == ["C", "B", "A", "D"]


def testRankRoutesKeepsUndrivableRoutesLast() -> None:
    ranked = rankRoutes([ROUTE_D, ROUTE_A])
    assert ids(ranked) == ["A", "D"]
    assert len(ranked) == 2


def testRankRoutesDoesNotModifyItsInput() -> None:
    routes = [ROUTE_D, ROUTE_A, ROUTE_B, ROUTE_C]
    rankRoutes(routes)
    assert ids(routes) == ["D", "A", "B", "C"]


def testRankRoutesEmptyAndSingle() -> None:
    assert rankRoutes([]) == []
    assert ids(rankRoutes([ROUTE_A])) == ["A"]


# --- decidingRule -------------------------------------------------------------


@pytest.mark.parametrize(
    ("best", "runnerUp", "expected"),
    [
        pytest.param(ROUTE_A, ROUTE_D, "the only drivable route", id="drivable"),
        pytest.param(ROUTE_B, ROUTE_A, "fewer severe miles (0.0 vs 40.0)", id="severe"),
        pytest.param(
            summary("X", high=10),
            summary("Y", high=30),
            "fewer high-risk miles (10.0 vs 30.0)",
            id="high",
        ),
        pytest.param(ROUTE_C, ROUTE_B, "lower average risk (0.70 vs 0.90)", id="average risk"),
        pytest.param(
            summary("X", hours=5.2),
            summary("Y", hours=5.5),
            "shorter travel time (5.2 h vs 5.5 h)",
            id="time",
        ),
        pytest.param(summary("X"), summary("Y"), "equal on every rule", id="tie"),
    ],
)
def testDecidingRule(best: RouteSummary, runnerUp: RouteSummary, expected: str) -> None:
    assert decidingRule(best, runnerUp) == expected


def testDecidingRuleUsesTheSameTolerancesAsRanking() -> None:
    """B vs C must be explained by average risk, not by C's 0.6 extra High miles."""
    assert decidingRule(ROUTE_C, ROUTE_B).startswith("lower average risk")


# --- recommendRoute -----------------------------------------------------------


def testRecommendRouteWorkedExample() -> None:
    ranked, reason = recommendRoute([ROUTE_A, ROUTE_B, ROUTE_C, ROUTE_D])
    assert ids(ranked) == ["C", "B", "A", "D"]
    assert reason == "Route C recommended over Route B: lower average risk (0.70 vs 0.90)."


def testRecommendRouteSingleRoute() -> None:
    ranked, reason = recommendRoute([ROUTE_B])
    assert ids(ranked) == ["B"]
    assert reason == "Route B is the only route available."


def testRecommendRouteOnlyDrivableRoute() -> None:
    _, reason = recommendRoute([ROUTE_D, ROUTE_A])
    assert reason == (
        "Route A recommended over Route D: the only drivable route, but it takes 12 min longer."
    )


def testRecommendRouteNoRouteIsSafe() -> None:
    blocked = summary("E", avgRisk=0.2, drivable=False)
    ranked, reason = recommendRoute([ROUTE_D, blocked])
    assert reason == "No route is safe to drive at this departure time."
    assert sorted(ids(ranked)) == ["D", "E"]  # still returned, so the UI can show why


def testRecommendRouteSingleBlockedRouteIsNotCalledAvailable() -> None:
    _, reason = recommendRoute([ROUTE_D])
    assert reason == "No route is safe to drive at this departure time."


def testRecommendRouteRejectsEmptyList() -> None:
    with pytest.raises(ValueError):
        recommendRoute([])


def testRecommendRouteFromGeneratedSummaries() -> None:
    """End to end from checkpoint risk levels to a recommendation."""
    calm = generateRouteSummary(
        "North", [0, 25, 50, 72], [R.LOW, R.LOW, R.MODERATE, R.LOW], 72, 5400
    )
    stormy = generateRouteSummary(
        "South", [0, 25, 50, 70], [R.LOW, R.SEVERE, R.HIGH, R.LOW], 70, 5000
    )
    ranked, reason = recommendRoute([stormy, calm])
    assert ids(ranked) == ["North", "South"]
    assert reason == (
        "Route North recommended over Route South: fewer severe miles (0.0 vs 25.0), "
        "but it takes 7 min longer."
    )


def testReasonSaysWhenTheSaferRouteIsMuchSlower() -> None:
    """The Casper -> Denver case: one Moderate stretch, the safe route is 3h 49m longer."""
    safe = summary("B", avgRisk=0.0, hours=37080 / 3600)
    fast = summary("A", avgRisk=0.09, hours=23340 / 3600)
    ranked, reason = recommendRoute([fast, safe])
    assert ids(ranked) == ["B", "A"]  # the brief's order still decides
    assert reason == (
        "Route B recommended over Route A: lower average risk (0.00 vs 0.09), "
        "but it takes 3h 49m longer."
    )


def testReasonHasNoTradeoffWhenTheBestRouteIsAlsoFaster() -> None:
    safe = summary("B", avgRisk=0.0, hours=3600 / 3600)
    risky = summary("A", avgRisk=0.5, hours=7200 / 3600)
    _, reason = recommendRoute([risky, safe])
    assert "longer" not in reason


def testReasonIgnoresLessThanAMinute() -> None:
    safe = summary("B", avgRisk=0.0, hours=3630 / 3600)
    risky = summary("A", avgRisk=0.5, hours=3600 / 3600)
    _, reason = recommendRoute([risky, safe])
    assert "longer" not in reason


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(60, "1 min"), (59 * 60, "59 min"), (3600, "1h 00m"), (13740, "3h 49m"), (90, "2 min")],
)
def testFormatDuration(seconds: float, expected: str) -> None:
    assert formatDuration(seconds) == expected
