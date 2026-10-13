from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


@dataclass(frozen=True)
class LoadRule:
    windMin: float
    windMax: float
    loadOverLb: float
    result: RiskLevel


# Conditions
WIND = [
    (25, RiskLevel.LOW),
    (35, RiskLevel.MODERATE),
    (45, RiskLevel.HIGH),
    (55, RiskLevel.SEVERE),
]  # >=55 is RiskLevel.NO_TRAVEL

RAIN = [
    (0.10, RiskLevel.LOW),
    (0.25, RiskLevel.MODERATE),
    (0.50, RiskLevel.HIGH),
    (1.00, RiskLevel.SEVERE),
]  # >1.00 is NO_TRAVEL

SNOW = [
    (0.5, RiskLevel.LOW),
    (1.00, RiskLevel.MODERATE),
    (2.00, RiskLevel.HIGH),
    (3.00, RiskLevel.SEVERE),
]  # >3.00 is NO_TRAVEL


LOAD_RULES = [
    LoadRule(windMin=45, windMax=55, loadOverLb=30000, result=RiskLevel.NO_TRAVEL),
    LoadRule(windMin=35, windMax=45, loadOverLb=40000, result=RiskLevel.SEVERE),
]


def bandLevel(
    value: float, bands: Sequence[tuple[float, RiskLevel]], maxInclusive: bool
) -> RiskLevel:
    for i, (upper, level) in enumerate(bands):
        isTop = i == len(bands) - 1
        if value < upper or (maxInclusive and isTop and value == upper):
            return level

    return RiskLevel.NO_TRAVEL


def applyLoadRules(base: RiskLevel, load: float, wind: float) -> RiskLevel:
    """base refers to curr max risk level considering the weather conditions"""
    level = base
    for rule in LOAD_RULES:
        if rule.windMin <= wind < rule.windMax and load > rule.loadOverLb:
            level = max(level, rule.result)
    return level


def classify(wind: float, rain: float, snow: float, load: float) -> RiskLevel:
    wind = round(wind, 2)
    rain = round(rain, 2)
    snow = round(snow, 2)
    base = max(
        bandLevel(wind, WIND, False), bandLevel(rain, RAIN, True), bandLevel(snow, SNOW, True)
    )

    classifiedLevel = applyLoadRules(base, load, wind)
    return classifiedLevel
