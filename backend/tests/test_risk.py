from itertools import pairwise

import pytest

from risk.engine import (
    LOAD_RULES,
    RAIN,
    SNOW,
    WIND,
    RiskLevel,
    applyLoadRules,
    bandLevel,
    classify,
)

R = RiskLevel


def caseId(value: object) -> str:
    """Readable test ids, e.g. `1.0-SEVERE` instead of `expected3`."""
    return value.name if isinstance(value, RiskLevel) else str(value)


# --- Band tables -----------------------------------------------------------
# Every edge is tested just below, exactly on, and just above the threshold.
# Lower edge is inclusive, upper edge exclusive; only the top of the rain and
# snow tables is inclusive (PDF: ">1.00" / ">3.0" is No Travel, but "≥55" for wind).


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, R.LOW),
        (24.99, R.LOW),
        (25, R.MODERATE),
        (34.99, R.MODERATE),
        (35, R.HIGH),
        (44.99, R.HIGH),
        (45, R.SEVERE),
        (54.99, R.SEVERE),
        (55, R.NO_TRAVEL),
        (80, R.NO_TRAVEL),
    ],
    ids=caseId,
)
def testWindBands(value: float, expected: RiskLevel) -> None:
    assert bandLevel(value, WIND, False) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, R.LOW),
        (0.09, R.LOW),
        (0.10, R.MODERATE),
        (0.24, R.MODERATE),
        (0.25, R.HIGH),
        (0.49, R.HIGH),
        (0.50, R.SEVERE),
        (0.99, R.SEVERE),
        (1.00, R.SEVERE),
        (1.01, R.NO_TRAVEL),
        (2.5, R.NO_TRAVEL),
    ],
    ids=caseId,
)
def testRainBands(value: float, expected: RiskLevel) -> None:
    assert bandLevel(value, RAIN, True) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, R.LOW),
        (0.49, R.LOW),
        (0.5, R.MODERATE),
        (0.99, R.MODERATE),
        (1.0, R.HIGH),
        (1.99, R.HIGH),
        (2.0, R.SEVERE),
        (2.99, R.SEVERE),
        (3.0, R.SEVERE),
        (3.01, R.NO_TRAVEL),
        (6, R.NO_TRAVEL),
    ],
    ids=caseId,
)
def testSnowBands(value: float, expected: RiskLevel) -> None:
    assert bandLevel(value, SNOW, True) == expected


@pytest.mark.parametrize(("name", "table"), [("WIND", WIND), ("RAIN", RAIN), ("SNOW", SNOW)])
def testTablesAreAscending(name: str, table: list[tuple[float, RiskLevel]]) -> None:
    """bandLevel returns at the first row the value is below, so row order matters."""
    thresholds = [upper for upper, _ in table]
    levels = [level for _, level in table]
    assert thresholds == sorted(thresholds), f"{name} thresholds out of order"
    assert levels == [R.LOW, R.MODERATE, R.HIGH, R.SEVERE], f"{name} levels out of order"


# --- Load rules ------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "wind", "load", "expected"),
    [
        pytest.param(R.SEVERE, 50, 30_001, R.NO_TRAVEL, id="45-54mph over 30k -> NO_TRAVEL"),
        pytest.param(R.SEVERE, 50, 30_000, R.SEVERE, id="45-54mph exactly 30k -> unchanged"),
        pytest.param(R.SEVERE, 45, 50_000, R.NO_TRAVEL, id="45mph lower edge triggers"),
        pytest.param(R.SEVERE, 54.99, 50_000, R.NO_TRAVEL, id="54.99mph upper edge triggers"),
        pytest.param(R.HIGH, 40, 40_001, R.SEVERE, id="35-44mph over 40k -> SEVERE"),
        pytest.param(R.HIGH, 40, 40_000, R.HIGH, id="35-44mph exactly 40k -> unchanged"),
        pytest.param(R.HIGH, 35, 45_000, R.SEVERE, id="35mph lower edge triggers"),
        pytest.param(R.HIGH, 40, 35_000, R.HIGH, id="35-44mph 35k -> unchanged"),
        pytest.param(R.MODERATE, 34.99, 80_000, R.MODERATE, id="below 35mph never triggers"),
        pytest.param(R.NO_TRAVEL, 40, 45_000, R.NO_TRAVEL, id="rule never downgrades"),
        pytest.param(R.LOW, 10, 80_000, R.LOW, id="heavy load in calm wind -> unchanged"),
    ],
)
def testApplyLoadRules(base: RiskLevel, wind: float, load: float, expected: RiskLevel) -> None:
    assert applyLoadRules(base, load=load, wind=wind) == expected


def testLoadRulesCoverDistinctWindRanges() -> None:
    """Rules must not overlap, otherwise one wind speed could match two rules."""
    ranges = sorted((rule.windMin, rule.windMax) for rule in LOAD_RULES)
    for (_, prevMax), (nextMin, _) in pairwise(ranges):
        assert prevMax <= nextMin


# --- classify: the public entry point --------------------------------------


@pytest.mark.parametrize(
    ("wind", "rain", "snow", "load", "expected"),
    [
        pytest.param(0, 0, 0, 0, R.LOW, id="all calm"),
        pytest.param(10, 0, 0, 10_000, R.LOW, id="light wind light load"),
        pytest.param(10, 0.30, 0, 10_000, R.HIGH, id="rain is the worst condition"),
        pytest.param(10, 0, 2.5, 10_000, R.SEVERE, id="snow is the worst condition"),
        pytest.param(30, 0.60, 0.7, 0, R.SEVERE, id="worst of three wins"),
        pytest.param(55, 0, 0, 0, R.NO_TRAVEL, id="55mph empty truck -> NO_TRAVEL"),
        pytest.param(40, 0, 0, 45_000, R.SEVERE, id="load rule raises HIGH to SEVERE"),
        pytest.param(40, 0, 0, 20_000, R.HIGH, id="light load keeps HIGH"),
        pytest.param(50, 0, 0, 30_000, R.SEVERE, id="exactly 30k keeps SEVERE"),
        pytest.param(50, 0, 0, 30_001, R.NO_TRAVEL, id="30,001 lb -> NO_TRAVEL"),
        pytest.param(40, 0, 3.5, 45_000, R.NO_TRAVEL, id="load rule cannot downgrade snow"),
        pytest.param(10, 0, 2.5, 45_000, R.SEVERE, id="heavy load does not lower snow"),
        pytest.param(0, 1.00, 0, 0, R.SEVERE, id="rain exactly 1.00 is SEVERE"),
        pytest.param(0, 0, 3.0, 0, R.SEVERE, id="snow exactly 3.0 is SEVERE"),
    ],
)
def testClassify(wind: float, rain: float, snow: float, load: float, expected: RiskLevel) -> None:
    assert classify(wind, rain, snow, load) == expected


@pytest.mark.parametrize(
    ("wind", "rain", "snow", "load", "expected"),
    [
        pytest.param(0, 0.2500000001, 0, 0, R.HIGH, id="float noise above 0.25 rounds to 0.25"),
        pytest.param(0, 0.0999999999, 0, 0, R.MODERATE, id="float noise below 0.10 rounds to 0.10"),
        pytest.param(54.999, 0, 0, 0, R.NO_TRAVEL, id="54.999mph rounds to 55"),
        pytest.param(34.999, 0, 0, 50_000, R.SEVERE, id="rounded wind also used by load rules"),
    ],
)
def testClassifyRoundsInputs(
    wind: float, rain: float, snow: float, load: float, expected: RiskLevel
) -> None:
    assert classify(wind, rain, snow, load) == expected


def testRiskLevelOrdering() -> None:
    """classify relies on max() picking the worst level."""
    assert R.LOW < R.MODERATE < R.HIGH < R.SEVERE < R.NO_TRAVEL
    assert max(R.HIGH, R.NO_TRAVEL, R.LOW) == R.NO_TRAVEL
