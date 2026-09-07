"""What the privacy-utility sweep says about a release the operator is looking at.

S3-3. The sweep produces a surface; this module is what makes it *actionable* at
the moment it matters — beside a published benchmark, answering "how much should
anyone trust this one?"

A generic curve on a page is a decoration. The number an operator needs is the
one for THEIR epsilon and THEIR cohort size, and the honest way to give it is to
say which measured cells their release falls between, rather than to interpolate
a figure that was never observed.

THE READING IS FROM SIMULATION, NOT FROM THIS RELEASE. The sweep ran on
synthetic cohorts drawn from the datagen process (evaluation/RESULTS.md section 9
states the limits). It says what releases at these parameters did across 200
trials. It does NOT say this particular release is 66.9% correct, and every
string this module produces is worded to keep that distinction.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

#: Ships inside the app rather than in evaluation/, so the dashboard can read it
#: from the container without depending on the repository layout.
SUMMARY_PATH = Path(__file__).resolve().parent / "data" / "sweep_summary.csv"


@dataclass(frozen=True)
class SweepCell:
    """One measured (epsilon, N) cell of the grid."""

    epsilon: Decimal
    n: int
    trials: int
    correct_quartile_rate: float
    unusable_rate: float
    rel_err_median_p50: float
    rel_err_median_p90: float

    @property
    def correct_percent(self) -> float:
        return self.correct_quartile_rate * 100

    @property
    def unusable_percent(self) -> float:
        return self.unusable_rate * 100

    @property
    def error_p90_percent(self) -> float:
        return self.rel_err_median_p90 * 100


@lru_cache(maxsize=1)
def sweep_cells() -> tuple[SweepCell, ...]:
    """The committed digest, read once.

    Cached because it is static data read on every dashboard render. An empty
    tuple when the file is absent: the dashboard degrades to not showing the
    guidance, rather than 500ing. A missing evaluation must not take the
    product down.
    """
    if not SUMMARY_PATH.exists():
        return ()

    with SUMMARY_PATH.open(encoding="utf-8") as fh:
        return tuple(
            SweepCell(
                epsilon=Decimal(row["epsilon"]),
                n=int(row["n"]),
                trials=int(row["trials"]),
                correct_quartile_rate=float(row["correct_quartile_rate"]),
                unusable_rate=float(row["unusable_rate"]),
                rel_err_median_p50=float(row["rel_err_median_p50"]),
                rel_err_median_p90=float(row["rel_err_median_p90"]),
            )
            for row in csv.DictReader(fh)
        )


def measured_epsilons() -> list[Decimal]:
    return sorted({cell.epsilon for cell in sweep_cells()})


def measured_cohort_sizes() -> list[int]:
    return sorted({cell.n for cell in sweep_cells()})


def cell_at(epsilon: Decimal, n: int) -> SweepCell | None:
    for cell in sweep_cells():
        if cell.epsilon == epsilon and cell.n == n:
            return cell
    return None


def _floor(value, grid: list):
    """Largest grid point at or below `value`, or None if `value` is below all."""
    below = [g for g in grid if g <= value]
    return max(below) if below else None


def _ceil(value, grid: list):
    """Smallest grid point at or above `value`, or None if `value` is above all."""
    above = [g for g in grid if g >= value]
    return min(above) if above else None


@dataclass(frozen=True)
class UtilityReading:
    """What the sweep says about a release at these parameters.

    `lower` is the pessimistic bracket and `upper` the optimistic one. When both
    are the same cell the release sits exactly on a measured point; when `upper`
    is None the release is beyond the grid's best measured cell, and the reading
    becomes a floor rather than a range.
    """

    epsilon: Decimal
    n: int
    lower: SweepCell | None
    upper: SweepCell | None

    @property
    def is_exact(self) -> bool:
        return self.lower is not None and self.lower is self.upper

    @property
    def has_reading(self) -> bool:
        return self.lower is not None or self.upper is not None

    @property
    def correct_quartile_range(self) -> tuple[float, float] | None:
        """(low, high) percent, or None when nothing can be said."""
        if self.lower is None and self.upper is None:
            return None
        if self.lower is None:
            # Below the measured grid entirely -- the only honest statement is
            # "no better than the worst cell measured".
            return (0.0, self.upper.correct_percent)
        if self.upper is None:
            return (self.lower.correct_percent, 100.0)
        low, high = self.lower.correct_percent, self.upper.correct_percent
        return (min(low, high), max(low, high))

    @property
    def beyond_grid(self) -> bool:
        """True when the release is more favourable than anything measured."""
        return self.lower is not None and self.upper is None


def reading_for(*, epsilon: Decimal, n: int) -> UtilityReading:
    """Bracket a release between the measured cells around it.

    Both dimensions are bracketed in the direction of utility: LOWER epsilon and
    FEWER contributors both make a release worse, so the pessimistic corner is
    (floor of epsilon, floor of N) and the optimistic one is (ceil, ceil).

    Nothing is interpolated. A reported figure is one that was actually observed
    in 200 trials at a real grid point, and the range between the brackets says
    honestly that the release sits somewhere in between.
    """
    epsilons, sizes = measured_epsilons(), measured_cohort_sizes()
    if not epsilons:
        return UtilityReading(epsilon=epsilon, n=n, lower=None, upper=None)

    floor_eps, floor_n = _floor(epsilon, epsilons), _floor(n, sizes)
    ceil_eps, ceil_n = _ceil(epsilon, epsilons), _ceil(n, sizes)

    lower = cell_at(floor_eps, floor_n) if floor_eps is not None and floor_n is not None else None
    upper = cell_at(ceil_eps, ceil_n) if ceil_eps is not None and ceil_n is not None else None
    return UtilityReading(epsilon=epsilon, n=n, lower=lower, upper=upper)


def curve_series() -> list[dict]:
    """The privacy-utility curve, one series per cohort size, for the chart.

    Shaped for the template rather than for a chart library: the dashboard
    renders it with the vendored Chart.js, and keeping the transformation here
    means the shape is testable without a browser.
    """
    series = []
    for n in measured_cohort_sizes():
        cells = sorted(
            (cell for cell in sweep_cells() if cell.n == n), key=lambda c: c.epsilon
        )
        series.append(
            {
                "n": n,
                "epsilons": [float(cell.epsilon) for cell in cells],
                "correct": [round(cell.correct_percent, 1) for cell in cells],
                "unusable": [round(cell.unusable_percent, 1) for cell in cells],
            }
        )
    return series
