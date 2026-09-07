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
