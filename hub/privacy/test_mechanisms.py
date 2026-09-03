"""Mechanism tests.

The category that catches the worst defect class in this project: code that
runs, returns plausible numbers, and provides no privacy at all. A DP release
that quietly returned the true value would pass every test about schemas,
transactions and ledgers in this repo.

Note what is NOT sufficient evidence. Comparing a released quantile against the
exact one proves nothing, because the exponential mechanism selects from a
200-point candidate grid while the exact quantile interpolates between observed
values -- the two differ even when no noise is applied at all. Randomness has to
be tested as randomness: the same input, released repeatedly, must not always
produce the same output, and the spread must shrink as epsilon grows.
"""

from __future__ import annotations

import statistics as stats
from decimal import Decimal

import opendp.prelude as dp
import polars as pl
import pytest

from privacy.mechanisms import get_mechanism, is_supported, supported_statistics
from privacy.mechanisms.registry import UnsupportedStatistic

VALUES = [3000.0, 3100.0, 3200.0, 3300.0, 3400.0, 3500.0, 3600.0, 3800.0]


def build_context(epsilon: float, queries: int = 1):
    return dp.Context.compositor(
        data=pl.LazyFrame({"value": VALUES}),
        privacy_unit=dp.unit_of(contributions=1),
        privacy_loss=dp.loss_of(epsilon=epsilon),
        split_evenly_over=queries,
        margins=[dp.polars.Margin(max_length=10_000)],
    )


def release_many(metric, statistic: str, epsilon: float, trials: int) -> list[float]:
    out = []
    for _ in range(trials):
        context = build_context(epsilon)
        outcome = get_mechanism(statistic).release(context, metric, Decimal(str(epsilon)))
        out.append(float(outcome.value))
    return out


# --- the registry ---------------------------------------------------------


def test_only_quantiles_are_registered_in_sprint_2():
    """Means and standard deviations are deliberately absent (SPEC section 6.1):
    far worse value per unit of epsilon. Shipping only the statistic that works
    is a position, not a gap."""
    assert supported_statistics() == ["median", "q25", "q75"]
    assert not is_supported("mean")
    assert not is_supported("stddev")


def test_an_unregistered_statistic_raises_rather_than_returning_nothing():
    with pytest.raises(UnsupportedStatistic, match="mean"):
        get_mechanism("mean")


def test_every_quantile_mechanism_reports_itself_as_exponential():
    """The ledger records the mechanism family. A wrong label would misdescribe
    what an auditor is looking at."""
    for statistic in supported_statistics():
        assert get_mechanism(statistic).mechanism_name == "exponential"


# --- noise is actually applied --------------------------------------------


@pytest.mark.django_db
def test_repeated_releases_of_identical_data_do_not_agree(metric):
    """The single most important assertion about the mechanism.

    Same data, same epsilon, released 30 times. If every answer is identical
    the mechanism is deterministic, which means it is returning a function of
    the data with no noise, which means there is no privacy -- however plausible
    the number looks.
    """
    released = release_many(metric, "median", epsilon=1.0, trials=30)

    assert len(set(released)) > 1, (
        f"30 releases of the same data all returned {released[0]} — "
        f"the mechanism is deterministic and provides no privacy"
    )


@pytest.mark.django_db
def test_noise_shrinks_as_epsilon_grows(metric):
    """Directional calibration.

    A weaker claim than matching the theoretical distribution, and chosen
    deliberately for a one-week sprint: it is cheap, and it fails loudly if the
    epsilon passed to OpenDP is ignored, hard-coded, or inverted. A mechanism
    whose spread does not respond to epsilon is not honouring the budget it was
    charged for.
    """
    tight = stats.pstdev(release_many(metric, "median", epsilon=8.0, trials=40))
    loose = stats.pstdev(release_many(metric, "median", epsilon=0.25, trials=40))

    assert loose > tight, (
        f"spread at epsilon=0.25 ({loose:.1f}) is not wider than at epsilon=8 "
        f"({tight:.1f}) — epsilon is not reaching the mechanism"
    )


@pytest.mark.django_db
def test_released_values_stay_within_the_public_bounds(metric):
    """The candidate grid comes from the metric's public bounds, so no release
    can fall outside them. A value outside would mean the grid was built from
    something else -- most likely the data, which would leak."""
    for value in release_many(metric, "q75", epsilon=1.0, trials=25):
        assert float(metric.lower_bound) <= value <= float(metric.upper_bound)


@pytest.mark.django_db
def test_the_candidate_grid_comes_from_bounds_not_data(metric):
    """Every released value must be one of the public candidates.

    This is what makes the grid auditable: an operator can reconstruct the full
    set of possible outputs from the catalog alone, without the data.
    """
    candidates = {round(c, 6) for c in metric.quantile_candidates()}

    for value in release_many(metric, "median", epsilon=1.0, trials=20):
        assert round(value, 6) in candidates


# --- summarize() ----------------------------------------------------------


@pytest.mark.django_db
def test_summarize_reports_a_scale_but_no_accuracy_for_quantiles(metric):
    """Pins ADR-0003 spike finding 4 as an executable fact.

    If a future OpenDP version starts returning an accuracy interval for the
    exponential mechanism, this test fails -- which is the notification we want,
    because the Sprint 3 simulation work (S2-5) would become unnecessary.
    """
    context = build_context(1.0)
    outcome = get_mechanism("median").release(context, metric, Decimal("1.0"))

    assert outcome.scale is not None and outcome.scale > 0
    assert outcome.accuracy_lower is None
    assert outcome.accuracy_upper is None
