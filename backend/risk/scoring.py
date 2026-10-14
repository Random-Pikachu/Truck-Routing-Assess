from dataclasses import dataclass
from functools import cmp_to_key

from risk.engine import RiskLevel

SEVERE_MILES_TOLERANCE = 1.0
HIGH_MILES_TOLERANCE = 1.0
AVG_RISK_TOLERANCE = 0.05


def toleranceChecker(x: float, y: float, tolerance: float) -> int:
    if abs(x - y) <= tolerance:
        return 0
    if x < y:
        return -1
    return 1


@dataclass()
class RouteSummary:
    routeId: str
    totalMiles: float
    totalSeconds: float
    milesPerRiskLvl: dict[RiskLevel, float]
    avgRisk: float
    drivable: bool


def ownedMiles(checkpointMiles: list[float], totalMiles: float) -> list[float]:
    owned = []
    last = len(checkpointMiles) - 1
    for i in range(len(checkpointMiles)):
        left = 0.0 if i == 0 else (checkpointMiles[i - 1] + checkpointMiles[i]) / 2
        right = totalMiles if i == last else (checkpointMiles[i] + checkpointMiles[i + 1]) / 2
        owned.append(right - left)

    return owned


def milesPerRisk(
    checkPointsRiskLvl: list[RiskLevel], milesOwned: list[float]
) -> tuple[dict[RiskLevel, float], float]:
    if not checkPointsRiskLvl:
        raise ValueError("A route needs at least one checkpoint")

    if len(checkPointsRiskLvl) != len(milesOwned):
        raise ValueError("Need one owned-miles value per checkpoint")

    milesByLevel = {level: 0.0 for level in RiskLevel}
    for i in range(len(checkPointsRiskLvl)):
        milesByLevel[checkPointsRiskLvl[i]] += milesOwned[i]

    totalMiles = sum(milesOwned)
    if totalMiles == 0:
        avgRisk = sum(checkPointsRiskLvl) / len(checkPointsRiskLvl)
    else:
        avgRisk = sum(level * miles for level, miles in milesByLevel.items()) / totalMiles

    return milesByLevel, avgRisk


def generateRouteSummary(
    routeId: str,
    checkpointMiles: list[float],
    checkPointsRiskLvl: list[RiskLevel],
    totalMiles: float,
    totalSeconds: float,
) -> RouteSummary:
    owned = ownedMiles(checkpointMiles, totalMiles)
    milesByLevel, avgRisk = milesPerRisk(checkPointsRiskLvl, owned)
    summary = RouteSummary(
        routeId=routeId,
        totalMiles=totalMiles,
        totalSeconds=totalSeconds,
        milesPerRiskLvl=milesByLevel,
        avgRisk=avgRisk,
        drivable=RiskLevel.NO_TRAVEL not in checkPointsRiskLvl,
    )

    return summary


def compareRoutes(a: RouteSummary, b: RouteSummary) -> int:
    """Which of two routes is better: -1 if `a`, 1 if `b`, 0 if they tie."""
    if a.drivable and not b.drivable:
        return -1
    if b.drivable and not a.drivable:
        return 1
    a_SevereMiles, b_SevereMiles = (
        a.milesPerRiskLvl[RiskLevel.SEVERE],
        b.milesPerRiskLvl[RiskLevel.SEVERE],
    )
    a_HighMiles, b_HighMiles = a.milesPerRiskLvl[RiskLevel.HIGH], b.milesPerRiskLvl[RiskLevel.HIGH]
    a_AvgRisk, b_AvgRisk = a.avgRisk, b.avgRisk

    # 0 -> tie, -1 -> a, 1->b
    compareSevMiles = toleranceChecker(a_SevereMiles, b_SevereMiles, SEVERE_MILES_TOLERANCE)
    compareHighMiles = toleranceChecker(a_HighMiles, b_HighMiles, HIGH_MILES_TOLERANCE)
    compareAvgRisks = toleranceChecker(a_AvgRisk, b_AvgRisk, AVG_RISK_TOLERANCE)

    if compareSevMiles != 0:
        return compareSevMiles
    if compareHighMiles != 0:
        return compareHighMiles
    if compareAvgRisks != 0:
        return compareAvgRisks
    return toleranceChecker(a.totalSeconds, b.totalSeconds, 0)


def rankRoutes(summaries: list[RouteSummary]) -> list[RouteSummary]:
    return sorted(summaries, key=cmp_to_key(compareRoutes))


def formatDuration(seconds: float) -> str:
    totalMinutes = round(seconds / 60)
    hours, minutes = divmod(totalMinutes, 60)
    if hours == 0:
        return f"{minutes} min"
    return f"{hours}h {minutes:02d}m"


def decidingRule(best: RouteSummary, runnerUp: RouteSummary) -> str:
    if best.drivable and not runnerUp.drivable:
        return "the only drivable route"

    bestSevere = best.milesPerRiskLvl[RiskLevel.SEVERE]
    runnerUpSevere = runnerUp.milesPerRiskLvl[RiskLevel.SEVERE]
    if toleranceChecker(bestSevere, runnerUpSevere, SEVERE_MILES_TOLERANCE) != 0:
        return f"fewer severe miles ({bestSevere:.1f} vs {runnerUpSevere:.1f})"

    bestHigh = best.milesPerRiskLvl[RiskLevel.HIGH]
    runnerUpHigh = runnerUp.milesPerRiskLvl[RiskLevel.HIGH]
    if toleranceChecker(bestHigh, runnerUpHigh, HIGH_MILES_TOLERANCE) != 0:
        return f"fewer high-risk miles ({bestHigh:.1f} vs {runnerUpHigh:.1f})"

    if toleranceChecker(best.avgRisk, runnerUp.avgRisk, AVG_RISK_TOLERANCE) != 0:
        return f"lower average risk ({best.avgRisk:.2f} vs {runnerUp.avgRisk:.2f})"

    if best.totalSeconds != runnerUp.totalSeconds:
        bestHours = best.totalSeconds / 3600
        runnerUpHours = runnerUp.totalSeconds / 3600
        return f"shorter travel time ({bestHours:.1f} h vs {runnerUpHours:.1f} h)"

    return "equal on every rule"


def recommendRoute(summaries: list[RouteSummary]) -> tuple[list[RouteSummary], str]:
    if not summaries:
        raise ValueError("Need at least one route to recommend")

    ranked = rankRoutes(summaries)
    best = ranked[0]

    if not best.drivable:
        return ranked, "No route is safe to drive at this departure time."
    if len(ranked) == 1:
        return ranked, f"Route {best.routeId} is the only route available."

    runnerUp = ranked[1]
    reason = f"Route {best.routeId} recommended over Route {runnerUp.routeId}: "
    reason += decidingRule(best, runnerUp)

    # the safer route can be a lot slower, say so instead of hiding it
    extraSeconds = best.totalSeconds - runnerUp.totalSeconds
    if extraSeconds >= 60:
        reason += f", but it takes {formatDuration(extraSeconds)} longer"
    return ranked, reason + "."
