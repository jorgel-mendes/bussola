"""Tests for the sweep reading shown beside a release (S3-3).

The failure mode here is not a crash. It is a number on a dashboard that claims
more than the experiment measured — an interpolated figure nobody observed, or a
reading that flatters a release by rounding its cohort up. Both would be read as
evidence, which is exactly what this project sells.

These run against the COMMITTED digest, not a fixture. The digest is the thing
the dashboard actually reads, and a test against a synthetic stand-in would pass
happily while the real file was malformed or missing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from benchmarks.utility import (
    SUMMARY_PATH,
    accuracy_band,
    bands_for,
    cell_at,
    curve_series,
    measured_cohort_sizes,
    measured_epsilons,
    reading_for,
    sweep_cells,
)

# --- the digest itself ------------------------------------------------------


def test_the_committed_digest_is_present_and_complete():
    """35 cells: 7 epsilons x 5 cohort sizes, all 200 trials."""
    cells = sweep_cells()

    assert SUMMARY_PATH.exists()
    assert len(cells) == 35
    assert len(measured_epsilons()) == 7
    assert len(measured_cohort_sizes()) == 5
    assert all(cell.trials == 200 for cell in cells)


def test_rates_are_proportions_not_percentages():
    """A digest written in percent would silently multiply every reading by 100."""
    assert all(0.0 <= cell.correct_quartile_rate <= 1.0 for cell in sweep_cells())
    assert all(0.0 <= cell.unusable_rate <= 1.0 for cell in sweep_cells())


def test_the_digest_agrees_with_the_published_results():
    """Spot-check against evaluation/RESULTS.md, which quotes these figures.

    The document and the file the dashboard reads must not drift: the write-up
    is what the article cites and the digest is what members are shown.
    """
    # To one decimal place, which is the precision RESULTS.md publishes and the
    # precision the dashboard displays. Asserting more would be asserting noise.
    assert cell_at(Decimal("1.0"), 25).correct_percent == pytest.approx(47.6, abs=0.05)
    assert cell_at(Decimal("2.0"), 100).correct_percent == pytest.approx(94.4, abs=0.05)
    assert cell_at(Decimal("1.0"), 50).unusable_percent == pytest.approx(5.0, abs=0.05)


def test_the_iso_utility_cells_are_in_the_digest():
    """The article's central finding: eps x N ~ 200 at 90%+ correct, 0% unusable."""
    for epsilon, n in ((Decimal("8.0"), 25), (Decimal("4.0"), 50), (Decimal("2.0"), 100)):
        cell = cell_at(epsilon, n)
        assert cell.correct_quartile_rate >= 0.90
        assert cell.unusable_rate == 0.0


# --- bracketing, and what it must never do ---------------------------------


def test_an_exact_grid_point_reads_as_a_single_cell():
    reading = reading_for(epsilon=Decimal("1.0"), n=50)

    assert reading.is_exact
    low, high = reading.correct_quartile_range
    assert low == high == pytest.approx(66.9, abs=0.05)


def test_a_release_between_cohort_sizes_is_reported_as_a_range(): 
    """47 contributors sits between the N=25 and N=50 cells.

    Reported as 47.6%-66.9%, not as an interpolated 60-something. Every figure
    the dashboard shows was observed in 200 real trials at a real grid point.
    """
    reading = reading_for(epsilon=Decimal("1.0"), n=47)

    low, high = reading.correct_quartile_range
    assert low == pytest.approx(47.6, abs=0.05)
    assert high == pytest.approx(66.9, abs=0.05)
    assert not reading.is_exact


def test_a_larger_cohort_is_never_rounded_up_into_a_better_reading():
    """The pessimistic bracket must come from the cohort size BELOW the release.

    Rounding 47 to 50 would report 66.9% for a release the sweep never measured
    and would flatter it by 19 points. The low end of the range must be the cell
    that is genuinely no better than this release.
    """
    reading = reading_for(epsilon=Decimal("1.0"), n=47)

    assert reading.lower.n == 25
    assert reading.upper.n == 50


def test_lower_epsilon_brackets_downward_too():
    """Less epsilon is more noise, so flooring epsilon is the pessimistic side."""
    reading = reading_for(epsilon=Decimal("1.5"), n=50)

    assert reading.lower.epsilon == Decimal("1.0")
    assert reading.upper.epsilon == Decimal("2.0")


def test_a_release_beyond_the_grid_reads_as_a_floor_not_a_promise():
    """106 contributors at eps=8 is better than anything measured.

    The honest statement is "at least as good as the best cell", never a
    fabricated 99%.
    """
    reading = reading_for(epsilon=Decimal("8.0"), n=106)

    assert reading.beyond_grid
    assert reading.upper is None
    low, high = reading.correct_quartile_range
    assert low == pytest.approx(97.7, abs=0.05)
    assert high == 100.0


def test_a_release_below_the_grid_claims_nothing_from_below():
    """Fewer contributors than the smallest cell measured. There is no floor to
    quote, so the range opens at zero rather than at the smallest measured
    figure — which would be a claim the sweep did not make."""
    reading = reading_for(epsilon=Decimal("1.0"), n=3)

    assert reading.lower is None
    low, _ = reading.correct_quartile_range
    assert low == 0.0


# --- the chart --------------------------------------------------------------


def test_curve_series_has_one_series_per_cohort_size():
    series = curve_series()

    assert [s["n"] for s in series] == measured_cohort_sizes()
    assert all(len(s["epsilons"]) == len(s["correct"]) == 7 for s in series)


def test_curve_series_is_ordered_by_epsilon():
    """A line chart plotted from unordered points draws a scribble."""
    for s in curve_series():
        assert s["epsilons"] == sorted(s["epsilons"])


# --- accuracy bands by simulation (S3-2) ------------------------------------
#
# Sprint 2 shipped no interval because a fabricated one is read as a promise.
# These tests exist so the interval that replaces it is not fabricated either.

BOUNDS = {"lower_bound": Decimal("1760"), "upper_bound": Decimal("7100")}


def test_the_band_brackets_the_true_value_not_the_noisy_one():
    """The inversion, which is the whole problem.

    The sweep measures error around a TRUE value it knows. An operator has the
    opposite: a noisy value in hand, and a true value they will never see. So
    for a released 3000 with 20% measured error, the true value sits in
    [3000/1.2, 3000/0.8] = [2500, 3750] — ASYMMETRIC about the release.

    `released * (1 ± e)` would give [2400, 3600]: symmetric, simpler, and an
    answer to a question nobody asked — the spread of noisy values around a
    known truth, which the operator already has.
    """
    band = accuracy_band(
        statistic="median", released=Decimal("3000"), relative_error=0.2, **BOUNDS
    )

    assert float(band.lower) == pytest.approx(2500.0, abs=0.5)
    assert float(band.upper) == pytest.approx(3750.0, abs=0.5)
    assert not band.clamped


def test_the_band_is_not_symmetric_about_the_released_value():
    """Stated as its own assertion because symmetry is the plausible bug: it
    looks right, and it is wrong in the direction that flatters the release."""
    band = accuracy_band(
        statistic="median", released=Decimal("3000"), relative_error=0.2, **BOUNDS
    )

    assert (band.upper - Decimal("3000")) > (Decimal("3000") - band.lower)


def test_the_band_never_claims_a_value_the_metric_bounds_exclude():
    """The correctness fix, found by reading the numbers the page would print.

    Inverting a 71% error on a released q75 of 3,800 gives an upper limit of
    12,996 MJ/t against a declared ceiling of 7,100. A submission above that
    ceiling is REJECTED at ingest rather than clamped, so the true quantile
    cannot be there — and a band claiming it might be asserts something the
    model already excludes.
    """
    band = accuracy_band(
        statistic="q75", released=Decimal("3800"), relative_error=0.71, **BOUNDS
    )

    assert band.upper == Decimal("7100")
    assert band.clamped


def test_an_error_over_100_percent_widens_to_the_declared_range_and_says_so():
    """true <= noisy / (1 - e) has no finite solution once e >= 1.

    Not hypothetical: at ε = 0.1 the measured q25 error exceeds 100% across the
    whole grid. The band becomes the entire catalogue range, which is the honest
    statement — this release constrains the answer not at all — and
    `spans_declared_range` exists so the page can say that instead of printing
    two numbers that look like a finding.
    """
    band = accuracy_band(
        statistic="q25", released=Decimal("3000"), relative_error=1.05, **BOUNDS
    )

    assert band.spans_declared_range
    assert band.lower == Decimal("1760") and band.upper == Decimal("7100")


def test_a_precise_release_does_not_span_the_declared_range():
    """The flag must distinguish, or it says nothing."""
    band = accuracy_band(
        statistic="median", released=Decimal("3400"), relative_error=0.01, **BOUNDS
    )

    assert not band.spans_declared_range
    assert not band.clamped


def test_the_lowest_epsilon_cells_really_are_unbounded():
    """Guards the case above against the digest changing under it."""
    assert cell_at(Decimal("0.1"), 25).p90_for("q25") >= 1.0


def test_each_statistic_uses_its_own_measured_error():
    """q25 is consistently the worst of the three; lending it the median's
    error would understate the uncertainty on the number members care most
    about — where the bottom of the distribution sits."""
    cell = cell_at(Decimal("1.0"), 50)

    assert cell.p90_for("q25") != cell.p90_for("median")
    assert cell.p90_for("count") is None


class _Stat:
    def __init__(self, statistic, value):
        self.statistic, self.value = statistic, value


class _Metric:
    lower_bound = Decimal("1760")
    upper_bound = Decimal("7100")


def test_bands_use_the_pessimistic_bracket():
    """A band too narrow to contain the truth is the failure that matters.

    An operator reading a tight interval concludes the release is precise. Too
    wide only costs confidence that was not earned, so the wider bracketing cell
    wins.
    """
    reading = reading_for(epsilon=Decimal("1.0"), n=47)  # brackets N=25 and N=50
    bands = bands_for([_Stat("median", Decimal("3400"))], reading, _Metric())

    assert bands["median"].relative_error == cell_at(Decimal("1.0"), 25).p90_for("median")
    assert bands["median"].relative_error > cell_at(Decimal("1.0"), 50).p90_for("median")


def test_no_bands_when_the_release_is_below_the_measured_grid():
    """Nothing measured means nothing claimed."""
    reading = reading_for(epsilon=Decimal("1.0"), n=3)

    assert bands_for([_Stat("median", Decimal("3400"))], reading, _Metric()) == {}


def test_a_negative_relative_error_is_refused():
    """It cannot happen from the sweep, which takes an absolute value. It would
    silently invert the band if it ever did."""
    with pytest.raises(ValueError, match="negative"):
        accuracy_band(
            statistic="median", released=Decimal("100"), relative_error=-0.1, **BOUNDS
        )


def test_inverted_metric_bounds_are_refused():
    """A clamp against nonsense bounds would produce a band with upper < lower,
    which renders as a range running backwards."""
    with pytest.raises(ValueError, match="Upper bound"):
        accuracy_band(
            statistic="median", released=Decimal("100"), relative_error=0.1,
            lower_bound=Decimal("7100"), upper_bound=Decimal("1760"),
        )
