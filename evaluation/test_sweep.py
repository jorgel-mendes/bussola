"""Tests for the privacy-utility sweep.

Two categories, and the split is the point.

FAST (unmarked, runs on every push): the measurement functions, against
hand-computed cases. These are the tests that matter most in this file. A defect
in `misassignment_rate` or `relative_error` does not crash anything and does not
fail the build -- it publishes a wrong finding in an article, which is a far
worse failure than a broken page. Retro action B3 applies: each of these was
verified by planting the defect it guards.

SLOW (marked `sweep`, deselected by default): the full grid. Seven epsilons x
five cohort sizes x 200 trials, each trial three OpenDP releases. It runs in its
own CI job, because adding it to the main suite would put every push behind it.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from evaluation import sweep

# --- the measurement functions ---------------------------------------------


def test_true_quantiles_match_the_shipped_exact_path():
    """The baseline is the product's own definition of the true value.

    Scoring against a different quantile definition -- numpy's, say -- would
    fold a definitional disagreement into what the article reports as the cost
    of privacy.
    """
    values = [Decimal(str(v)) for v in (1, 2, 3, 4, 5)]
    true = sweep.true_quantiles(values)

    assert true["q25"] == Decimal("2")
    assert true["median"] == Decimal("3")
    assert true["q75"] == Decimal("4")


def test_true_quantiles_are_order_independent():
    """The caller must not have to pre-sort."""
    shuffled = [Decimal(str(v)) for v in (5, 1, 4, 2, 3)]
    assert sweep.true_quantiles(shuffled) == sweep.true_quantiles(
        sorted(shuffled)
    )


def test_relative_error_is_the_absolute_gap_over_the_true_value():
    assert sweep.relative_error(Decimal("110"), Decimal("100")) == pytest.approx(0.1)
    # Symmetric: a release 10% low costs the same as one 10% high.
    assert sweep.relative_error(Decimal("90"), Decimal("100")) == pytest.approx(0.1)


def test_relative_error_refuses_a_zero_true_value():
    """Undefined, and a silent inf or nan would poison every aggregate."""
    with pytest.raises(ValueError, match="undefined"):
        sweep.relative_error(Decimal("1"), Decimal("0"))


def test_misassignment_rate_is_zero_when_the_release_is_exact():
    values = [Decimal(str(v)) for v in range(1, 101)]
    true = sweep.true_quantiles(values)

    assert sweep.misassignment_rate(values, true, true) == 0.0


def test_misassignment_counts_only_contributors_whose_quartile_moved():
    """Hand-computed: the noisy q25 drags exactly one contributor out of Q1.

    True boundaries over 1..8 are q25=2.75, median=4.5, q75=6.25, so 1 and 2 are
    Q1. Moving the released q25 down to 1.5 leaves only 1 in Q1 and pushes 2
    into Q2 -- one contributor of eight, and nothing else moves.
    """
    values = [Decimal(str(v)) for v in range(1, 9)]
    true = sweep.true_quantiles(values)
    noisy = dict(true, q25=Decimal("1.5"))

    assert sweep.misassignment_rate(values, true, noisy) == pytest.approx(1 / 8)


def test_misassignment_rate_refuses_an_empty_cohort():
    """A rate over zero contributors is not 0.0, it is meaningless.

    Returning 0.0 would report a perfect score for a cell that measured nothing,
    and perfect scores are exactly what nobody re-checks.
    """
    true = {"q25": Decimal("1"), "median": Decimal("2"), "q75": Decimal("3")}
    with pytest.raises(ValueError, match="no contributors"):
        sweep.misassignment_rate([], true, true)


def test_a_wholly_inverted_release_misassigns_nearly_everyone():
    """The unusable case scores as badly as it reads."""
    values = [Decimal(str(v)) for v in range(1, 101)]
    true = sweep.true_quantiles(values)
    inverted = {"q25": true["q75"], "median": true["median"], "q75": true["q25"]}

    assert sweep.misassignment_rate(values, true, inverted) > 0.4


# --- the usability rule, shared with the dashboard -------------------------


def test_ordering_check_accepts_a_monotone_triple():
    ordered = {"q25": Decimal("1"), "median": Decimal("2"), "q75": Decimal("3")}
    assert sweep.quantiles_ordered(ordered) is True


def test_ordering_check_rejects_the_sprint_2_inversion():
    """The real numbers from the deployed hub's six-contributor cohort."""
    observed = {"q25": Decimal("158.5"), "median": Decimal("190.9"), "q75": Decimal("73.4")}
    assert sweep.quantiles_ordered(observed) is False


# --- the sampling process --------------------------------------------------


def test_sample_cohort_is_reproducible_from_its_seed():
    """A figure in the article must be reproducible from the seed beside it."""
    import random

    first = sweep.sample_cohort(20, random.Random("fixed"))
    second = sweep.sample_cohort(20, random.Random("fixed"))
    assert first == second


def test_sample_cohort_respects_the_metric_bounds():
    """Values outside the declared bounds would be clamped by the mechanism
    anyway; generating them would silently change the distribution."""
    import random

    values = sweep.sample_cohort(500, random.Random("bounds"))
    assert all(sweep.LOWER_BOUND <= v <= sweep.UPPER_BOUND for v in values)


def test_sweep_distribution_has_not_drifted_from_datagen():
    """The sweep's generative process must match the one that seeds the demo.

    Loaded by path under a private name and unregistered afterwards -- the same
    technique as hub/contributors/test_seed_demo.py, and for the same reason: a
    sys.path.insert leaks into every later test in the process, and caches the
    module under a name a later import reuses.
    """
    datagen = Path(__file__).resolve().parents[1] / "datagen" / "generate.py"
    spec = importlib.util.spec_from_file_location("_datagen_generate", datagen)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        thermal = module.METRICS[0]
    finally:
        sys.modules.pop(spec.name, None)

    assert thermal.code == sweep.METRIC_CODE
    assert thermal.sector_mean == sweep.SECTOR_MEAN
    assert thermal.sector_sigma == sweep.SECTOR_SIGMA
    assert Decimal(str(thermal.lower_bound)) == sweep.LOWER_BOUND
    assert Decimal(str(thermal.upper_bound)) == sweep.UPPER_BOUND


def test_sweep_metric_is_never_saved():
    """The sweep must not be able to touch the database.

    An unsaved instance keeps 7,000 simulated releases out of the audit trail,
    and lets the sweep's CI job run without Postgres at all.
    """
    metric = sweep.sweep_metric()
    assert metric.pk is None


# --- aggregation -----------------------------------------------------------


def _trial(**overrides):
    defaults = {
        "epsilon": "1.0",
        "n": 25,
        "trial": 0,
        "epsilon_per_statistic": "0.333334",
        "true_q25": 1.0,
        "true_median": 2.0,
        "true_q75": 3.0,
        "noisy_q25": 1.0,
        "noisy_median": 2.0,
        "noisy_q75": 3.0,
        "rel_err_q25": 0.0,
        "rel_err_median": 0.0,
        "rel_err_q75": 0.0,
        "misassignment_rate": 0.0,
        "ordered": True,
    }
    return sweep.TrialResult(**{**defaults, **overrides})


def test_correct_quartile_rate_is_the_complement_of_misassignment():
    """This is the demo headline sentence; it must not be off by anything."""
    results = [_trial(misassignment_rate=0.04) for _ in range(10)]
    summary = sweep.summarize_cell(results)

    assert summary.mean_misassignment_rate == pytest.approx(0.04)
    assert summary.correct_quartile_rate == pytest.approx(0.96)


def test_unusable_rate_counts_inverted_releases():
    results = [_trial(ordered=True) for _ in range(7)] + [
        _trial(ordered=False) for _ in range(3)
    ]
    assert sweep.summarize_cell(results).unusable_rate == pytest.approx(0.3)


def test_summarize_refuses_an_empty_cell():
    with pytest.raises(ValueError, match="empty cell"):
        sweep.summarize_cell([])


def test_summarize_groups_by_epsilon_and_n():
    results = [
        _trial(epsilon="1.0", n=25),
        _trial(epsilon="1.0", n=50),
        _trial(epsilon="2.0", n=25),
    ]
    assert len(sweep.summarize(results)) == 3


def test_csv_carries_one_row_per_trial(tmp_path):
    """Per-trial rows, so the article can recompute any aggregate later."""
    import csv

    path = sweep.write_csv([_trial(trial=i) for i in range(5)], tmp_path / "s.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))

    assert len(rows) == 5
    assert set(rows[0]) == set(sweep.CSV_FIELDS)


# --- one real release, end to end (fast enough for every push) -------------


def test_a_real_release_produces_a_scored_trial():
    """One genuine OpenDP release through the shipped mechanism.

    Three releases at ~450ms each, so it costs about a second and a half -- worth
    paying on every push, because it is the test that fails if the sweep and the
    release path stop agreeing about how a context is built.
    """
    import random

    values = sweep.sample_cohort(50, random.Random("smoke"))
    result = sweep.run_trial(epsilon=Decimal("1.0"), values=values, trial=0)

    assert result.n == 50
    assert result.epsilon_per_statistic == "0.333334"
    assert sweep.LOWER_BOUND <= Decimal(str(result.noisy_median)) <= sweep.UPPER_BOUND
    assert 0.0 <= result.misassignment_rate <= 1.0


def test_a_release_is_noisy_rather_than_exact():
    """Guards the catastrophic failure: a mechanism that applies no noise.

    Verified by planting it -- returning the true quantile makes this fail.
    Two releases of identical data must disagree somewhere.
    """
    import random

    values = sweep.sample_cohort(50, random.Random("noise"))
    first = sweep.run_trial(epsilon=Decimal("0.5"), values=values, trial=0)
    second = sweep.run_trial(epsilon=Decimal("0.5"), values=values, trial=1)

    assert (first.noisy_q25, first.noisy_median, first.noisy_q75) != (
        second.noisy_q25,
        second.noisy_median,
        second.noisy_q75,
    )


# --- the sweep must price privacy the way the product does ------------------
#
# These two exist because of a planted defect that NOTHING ELSE CAUGHT.
# Multiplying the context's epsilon by ten in run_trial -- so the sweep measured
# a privacy level ten times more generous than the hub actually spends -- left
# all 21 tests green. Every figure in the article would have been wrong, in the
# flattering direction, with a clean build behind it.
#
# The lesson is Sprint 2's B1 arriving from a new angle: the suite asserted that
# a release is noisy, and that the charge is split correctly, but never that the
# noise and the charge refer to the SAME epsilon.


def test_the_context_runs_at_exactly_the_epsilon_that_is_charged(monkeypatch):
    """The privacy actually spent must equal the price the ledger would record.

    A sweep that ran its mechanism at a different epsilon from the one it
    reports would not be measuring the product -- it would be measuring a more
    (or less) private system that nobody ships, and no other test would notice.
    """
    seen = {}
    real = sweep.build_context

    def spy(values, **kwargs):
        seen.update(kwargs)
        return real(values, **kwargs)

    monkeypatch.setattr(sweep, "build_context", spy)

    import random

    values = sweep.sample_cohort(20, random.Random("price"))
    result = sweep.run_trial(epsilon=Decimal("1.0"), values=values, trial=0)

    charged = Decimal(result.epsilon_per_statistic) * len(sweep.QUANTILE_STATISTICS)
    assert Decimal(str(seen["epsilon"])) == charged
    assert seen["split_evenly_over"] == len(sweep.QUANTILE_STATISTICS)


def test_the_privacy_unit_is_the_one_the_catalog_declares(monkeypatch):
    """One contributor, one row. A sweep run at a looser privacy unit would
    understate the noise for the same reason -- silently, and only in the
    direction that makes the results look better."""
    seen = {}
    real = sweep.build_context

    def spy(values, **kwargs):
        seen.update(kwargs)
        return real(values, **kwargs)

    monkeypatch.setattr(sweep, "build_context", spy)

    import random

    sweep.run_trial(
        epsilon=Decimal("1.0"), values=sweep.sample_cohort(20, random.Random("unit")), trial=0
    )

    assert seen["contributions"] == sweep.CONTRIBUTIONS_PER_PERIOD == 1


# --- the grid ---------------------------------------------------------------


@pytest.mark.sweep
@pytest.mark.parametrize("epsilon", sweep.EPSILONS, ids=str)
@pytest.mark.parametrize("n", sweep.CONTRIBUTOR_COUNTS, ids=str)
def test_sweep_cell(epsilon, n, sweep_writer):
    """One cell of the grid, appended to the CSV.

    Parameterised per cell rather than per trial: 35 test items that each run
    200 trials, so a failure names the (epsilon, N) that broke and the run
    stays legible.
    """
    results = sweep.run_cell(epsilon=epsilon, n=n)
    sweep_writer(results)

    summary = sweep.summarize_cell(results)
    assert summary.trials == sweep.DEFAULT_TRIALS
    # No assertion on accuracy. The sweep MEASURES the privacy-utility
    # trade-off; asserting a floor on it would turn an experiment into a test
    # that fails when the answer is inconvenient.
    assert 0.0 <= summary.correct_quartile_rate <= 1.0
