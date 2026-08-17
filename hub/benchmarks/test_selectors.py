"""Benchmark computation tests.

These pin the *exact* Sprint 1 behaviour. In Sprint 2 the same cells are
computed under differential privacy, and these become the ground-truth baseline
the privacy-utility evaluation measures error against — so the expected values
here are deliberately hand-checkable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from benchmarks.selectors import compute_exact_benchmark, contributor_position
from collaborations.models import Cohort
from contributors.models import Contributor
from ingest.models import Submission

pytestmark = pytest.mark.django_db


VALUES = ["2900", "3100", "3300", "3500", "3700", "3900", "4100"]


def test_suppressed_below_minimum_contributors(cohort, metric, period, make_contributors):
    """INVARIANT: a cell with too few contributors is not published at all.

    Conventional statistical disclosure control — with two contributors, a
    'benchmark' is just their values.
    """
    make_contributors(metric, period, ["2900", "3300"])
    result = compute_exact_benchmark(cohort, metric, period)
    assert result.suppressed
    assert result.q25 is None and result.median is None and result.q75 is None
    assert "Fewer than 5" in result.suppression_reason


def test_published_at_or_above_minimum_contributors(cohort, metric, period, make_contributors):
    make_contributors(metric, period, ["2900", "3100", "3300", "3500", "3700"])
    result = compute_exact_benchmark(cohort, metric, period)
    assert not result.suppressed
    assert result.n_contributors == 5
    assert result.median == Decimal("3300")


def test_threshold_is_per_collaboration(collaboration, cohort, metric, period, make_contributors):
    """The threshold lives on the Collaboration, not in global settings.

    A 12-plant consortium and a 400-hospital study need different thresholds,
    and one deployment may host both.
    """
    collaboration.min_contributors = 3
    collaboration.save(update_fields=["min_contributors"])

    make_contributors(metric, period, ["2900", "3300", "3700"])
    result = compute_exact_benchmark(cohort, metric, period)
    assert not result.suppressed
    assert result.min_contributors == 3


def test_quartiles_on_a_known_series(cohort, metric, period, make_contributors):
    """Seven evenly spaced values: quartiles land on data points exactly."""
    make_contributors(metric, period, VALUES)
    result = compute_exact_benchmark(cohort, metric, period)
    assert result.minimum == Decimal("2900")
    assert result.q25 == Decimal("3200")
    assert result.median == Decimal("3500")
    assert result.q75 == Decimal("3800")
    assert result.maximum == Decimal("4100")


def test_inactive_contributors_are_excluded(cohort, metric, period, make_contributors):
    made = make_contributors(metric, period, VALUES)
    made[0].is_active = False
    made[0].save(update_fields=["is_active"])
    result = compute_exact_benchmark(cohort, metric, period)
    assert result.n_contributors == len(VALUES) - 1


def test_other_cohorts_do_not_leak_into_a_benchmark(
    collaboration, cohort, metric, period, make_contributors
):
    """Cross-cohort contamination would be a disclosure, not just a wrong number."""
    make_contributors(metric, period, VALUES)

    other_cohort = Cohort.objects.create(
        collaboration=collaboration, code="9999", name="Unrelated"
    )
    outsider = Contributor.objects.create(
        collaboration=collaboration, name="Outsider", cohort=other_cohort
    )
    Submission.objects.create(
        contributor=outsider, period=period, metric=metric,
        value=Decimal("6800"), n_records=30, agent_version="t",
    )

    result = compute_exact_benchmark(cohort, metric, period)
    assert result.n_contributors == len(VALUES)
    assert result.maximum == Decimal("4100")


def test_refuses_to_compute_across_collaborations(
    cohort, metric, period, other_collaboration, make_contributors
):
    """INVARIANT: a cell must not straddle two collaborations.

    Mixing them would combine separate privacy budgets and publish one group's
    data inside another group's benchmark.
    """
    from catalog.models import MetricDefinition

    foreign_metric = MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="energy_per_tonne",
        name="Same code, different collaboration",
        unit="kWh/t",
        lower_bound=Decimal("1"),
        upper_bound=Decimal("2"),
        bounds_rationale="Unrelated study.",
    )

    with pytest.raises(ValueError, match="same collaboration"):
        compute_exact_benchmark(cohort, foreign_metric, period)


def test_contributor_position_assigns_quartiles(cohort, metric, period, make_contributors):
    make_contributors(metric, period, VALUES)
    result = compute_exact_benchmark(cohort, metric, period)
    assert contributor_position(Decimal("2950"), result) == "Q1"
    assert contributor_position(Decimal("3400"), result) == "Q2"
    assert contributor_position(Decimal("3750"), result) == "Q3"
    assert contributor_position(Decimal("4050"), result) == "Q4"


def test_contributor_position_is_unknown_when_suppressed(
    cohort, metric, period, make_contributors
):
    make_contributors(metric, period, ["2900", "3300"])
    result = compute_exact_benchmark(cohort, metric, period)
    assert contributor_position(Decimal("3000"), result) == "unknown"


def test_result_is_flagged_as_exact(cohort, metric, period, make_contributors):
    """Sprint 1 output must self-identify as un-noised, so no later code can
    mistake it for a privacy-protected release."""
    make_contributors(metric, period, VALUES)
    assert compute_exact_benchmark(cohort, metric, period).is_exact is True
