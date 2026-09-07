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
    rel_err_q25_p90: float
    rel_err_q75_p90: float

    def p90_for(self, statistic: str) -> float | None:
        """The 90th-percentile relative error measured for one statistic.

        None for anything the sweep did not measure. A statistic without a
        measured error distribution must show no band rather than borrow another
        statistic's — the quartiles do not have the same error, and q25 is
        consistently the worst of the three.
        """
        return {
            "q25": self.rel_err_q25_p90,
            "median": self.rel_err_median_p90,
            "q75": self.rel_err_q75_p90,
        }.get(statistic)

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
                rel_err_q25_p90=float(row["rel_err_q25_p90"]),
                rel_err_q75_p90=float(row["rel_err_q75_p90"]),
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


# --- accuracy bands by simulation (S3-2 / S2-5) -----------------------------
#
# Sprint 2 shipped no interval, for a stated reason: OpenDP's summarize()
# returns none for the exponential mechanism, and a fabricated interval is read
# as a promise. The sweep is the simulation that was owed.
#
# THE INVERSION IS THE WHOLE PROBLEM, and getting it wrong is the easy mistake.
# The sweep measures  |noisy - true| / true  -- error around a true value that
# the experiment knows. An operator has the opposite: a noisy value in hand and
# a true value they will never see. So the band must be inverted, not mirrored:
#
#     |noisy - true| <= e * true
#       =>  true(1 - e) <= noisy <= true(1 + e)
#       =>  noisy / (1 + e) <= true <= noisy / (1 - e)
#
# Which is ASYMMETRIC about the released value, and unbounded above once
# e >= 1. Writing `released * (1 +/- e)` would look right, be symmetric, be
# simpler, and answer a question nobody asked: the spread of noisy values around
# a known truth, which the operator already has.


@dataclass(frozen=True)
class AccuracyBand:
    """Where the true value plausibly sits, given the released one.

    `lower` and `upper` bracket the TRUE value, clamped to the metric's declared
    bounds. `spans_declared_range` marks the case where the band has widened to
    the whole catalogue range -- the release constrains the answer not at all,
    and saying that plainly beats printing two numbers that look like a finding.
    """

    statistic: str
    released: Decimal
    relative_error: float
    lower: Decimal
    upper: Decimal
    clamped: bool
    spans_declared_range: bool

    @property
    def percent(self) -> float:
        return self.relative_error * 100


def accuracy_band(
    *,
    statistic: str,
    released: Decimal,
    relative_error: float,
    lower_bound: Decimal,
    upper_bound: Decimal,
) -> AccuracyBand:
    """Invert a measured relative error into a band on the TRUE value.

    CLAMPED TO THE METRIC'S DECLARED BOUNDS, and that is a correctness fix
    rather than cosmetics. Inverting a 71% error on a released q75 of 3,800
    gives an upper limit of 12,996 MJ/t -- against a declared ceiling of 7,100.
    A submission above that ceiling is rejected at ingest rather than clamped
    (ingest.views), so the true quantile cannot be there, and a band claiming it
    might be would be asserting something the model already excludes.

    The bounds are public domain knowledge, already displayed beside every
    benchmark and already the basis of the mechanism's candidate grid. Using
    them here narrows the band with information the reader already has, which is
    the opposite of fabricating one.

    When the measured error reaches 100% the upper limit is infinite before
    clamping; the band then becomes the entire declared range, and
    `spans_declared_range` says so.
    """
    if relative_error < 0:
        raise ValueError("Relative error cannot be negative.")
    if upper_bound <= lower_bound:
        raise ValueError("Upper bound must exceed lower bound.")

    error = Decimal(str(relative_error))
    raw_lower = released / (Decimal(1) + error)
    # true <= noisy / (1 - e) has no finite solution once e >= 1.
    raw_upper = None if error >= 1 else released / (Decimal(1) - error)

    lower = max(raw_lower, lower_bound)
    upper = upper_bound if raw_upper is None else min(raw_upper, upper_bound)

    clamped = raw_lower < lower_bound or raw_upper is None or raw_upper > upper_bound
    declared_width = upper_bound - lower_bound
    return AccuracyBand(
        statistic=statistic,
        released=released,
        relative_error=relative_error,
        lower=lower,
        upper=upper,
        clamped=clamped,
        # 95% of the catalogue range is indistinguishable from all of it for a
        # reader deciding whether to act on the number.
        spans_declared_range=(upper - lower) >= declared_width * Decimal("0.95"),
    )


def bands_for(statistics, reading: UtilityReading | None, metric=None) -> dict[str, AccuracyBand]:
    """Band each released statistic, using the PESSIMISTIC bracket.

    The wider of the two bracketing cells, deliberately. A band is a claim about
    where the truth might be, and the failure that matters is a band too narrow
    to contain it -- an operator reading a tight interval concludes the release
    is precise. Too wide only costs confidence that was not earned.
    """
    if reading is None or reading.lower is None or metric is None:
        return {}

    bands = {}
    for statistic in statistics:
        p90 = reading.lower.p90_for(statistic.statistic)
        if p90 is None:
            continue
        bands[statistic.statistic] = accuracy_band(
            statistic=statistic.statistic,
            released=statistic.value,
            relative_error=p90,
            lower_bound=metric.lower_bound,
            upper_bound=metric.upper_bound,
        )
    return bands
