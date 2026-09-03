"""The DP release path, and the invariant it exists to hold.

    the release and its ledger entries are written in ONE transaction

Stated in both directions, because each direction is a different failure:

  * a release with no ledger entry  -> unaccounted privacy loss. Epsilon was
    spent, a number was published, and the budget does not know. Every later
    release is then authorised against a total that is wrong.
  * a ledger entry with no release  -> a charge for a disclosure nobody
    received. Budget is consumed by nothing, and the audit trail claims a
    publication that does not exist.

The first is the serious one. Both are tested.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from benchmarks.models import BenchmarkRelease, ReleasedStatistic
from benchmarks.releases import release_benchmark, statistics_to_release
from budget.exceptions import BudgetExhausted
from budget.models import BudgetPeriod, LedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def budget(period) -> BudgetPeriod:
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("5.0000"))


@pytest.fixture
def cell(cohort, metric, period, make_contributors):
    """A publishable cell: 8 contributors, above the threshold of 5."""
    make_contributors(
        metric, period, ["3000", "3100", "3200", "3300", "3400", "3500", "3600", "3800"]
    )
    return {"cohort": cohort, "metric": metric, "period": period}


def do_release(cell, epsilon="1.500000"):
    return release_benchmark(
        cohort=cell["cohort"],
        metric=cell["metric"],
        period=cell["period"],
        epsilon=Decimal(epsilon),
    )


# --- the invariant, both directions ---------------------------------------


def test_every_released_statistic_has_a_ledger_entry(budget, cell):
    """Direction 1: no unaccounted privacy loss."""
    outcome = do_release(cell)

    assert not outcome.suppressed
    statistics = ReleasedStatistic.objects.filter(release=outcome.release)
    entries = LedgerEntry.objects.filter(release=outcome.release)

    assert statistics.count() == entries.count() > 0
    assert {s.statistic for s in statistics} == {e.statistic for e in entries}


def test_every_ledger_entry_has_a_release(budget, cell):
    """Direction 2: no charge for a disclosure nobody received.

    Enforced at the database level too -- LedgerEntry.release is NOT NULL --
    but asserted here because the column being non-nullable is only half of it.
    """
    do_release(cell)

    assert LedgerEntry.objects.filter(release__isnull=True).count() == 0
    for entry in LedgerEntry.objects.all():
        assert entry.release is not None


def test_the_ledger_total_equals_the_release_epsilon(budget, cell):
    """The two records of the same fact must agree."""
    outcome = do_release(cell, "1.500000")

    from django.db.models import Sum

    ledger_total = LedgerEntry.objects.filter(release=outcome.release).aggregate(
        t=Sum("epsilon_spent")
    )["t"]

    assert ledger_total == outcome.release.epsilon_spent
    assert budget.spent() == outcome.release.epsilon_spent


def test_a_failure_mid_release_leaves_nothing_behind(budget, cell, monkeypatch):
    """The transaction doing its job.

    If the mechanism blows up after some statistics are published and charged,
    the release, its statistics and its ledger entries must all disappear
    together. A half-published release whose budget was charged is exactly the
    unaccounted state the invariant forbids.
    """
    import benchmarks.releases as releases_module

    real_get = releases_module.get_mechanism
    calls = {"n": 0}

    def exploding_get(statistic):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("mechanism failed on the second statistic")
        return real_get(statistic)

    monkeypatch.setattr(releases_module, "get_mechanism", exploding_get)

    with pytest.raises(RuntimeError, match="second statistic"):
        do_release(cell)

    assert BenchmarkRelease.objects.count() == 0
    assert ReleasedStatistic.objects.count() == 0
    assert LedgerEntry.objects.count() == 0
    assert budget.spent() == Decimal("0")


def test_budget_exhaustion_mid_release_publishes_nothing(cell, period):
    """A partial release is worse than none.

    The budget affords one statistic of three. The correct outcome is that the
    whole release is refused -- publishing q25 alone, having charged for it,
    would leave the member with a number they cannot interpret and the operator
    with a drawn-down budget for an incomplete answer.
    """
    BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("0.6000"))

    with pytest.raises(BudgetExhausted):
        do_release(cell, "1.500000")

    assert BenchmarkRelease.objects.count() == 0
    assert LedgerEntry.objects.count() == 0


# --- suppression comes before any spend -----------------------------------


def test_a_suppressed_cell_costs_no_budget(budget, cohort, metric, period, make_contributors):
    """Charging for a refused release would drain the budget through cells that
    were never published."""
    make_contributors(metric, period, ["3000", "3100"])  # 2 < 5

    outcome = release_benchmark(
        cohort=cohort, metric=metric, period=period, epsilon=Decimal("1.500000")
    )

    assert outcome.suppressed
    assert outcome.release is None
    assert budget.spent() == Decimal("0")
    assert BenchmarkRelease.objects.count() == 0
    assert LedgerEntry.objects.count() == 0


# --- what actually gets published -----------------------------------------


def test_the_released_values_land_inside_the_declared_bounds(budget, cell, metric):
    """A released quantile is chosen from the public candidate grid, so it can
    never fall outside the metric's declared bounds. If it did, the grid was
    built from something other than the bounds -- most likely the data."""
    outcome = do_release(cell)

    for statistic in outcome.statistics:
        assert metric.lower_bound <= statistic.value <= metric.upper_bound


def test_the_contributor_count_is_published_exactly(budget, cell):
    """Membership is public, so noising the count buys no privacy and costs
    accuracy (DESIGN.md section 2.2)."""
    outcome = do_release(cell)

    assert outcome.release.n_contributors == 8


def test_unsupported_statistics_are_reported_not_silently_dropped(budget, cell, metric):
    """An operator must not believe they published something they did not."""
    metric.statistics = ["count", "q25", "median", "q75", "mean"]
    metric.save()

    outcome = do_release(cell)

    assert sorted(s.statistic for s in outcome.statistics) == ["median", "q25", "q75"]
    assert sorted(outcome.skipped_statistics) == ["count", "mean"]


def test_statistics_to_release_splits_the_catalog(metric):
    metric.statistics = ["count", "median", "stddev"]
    releasable, skipped = statistics_to_release(metric)

    assert releasable == ["median"]
    assert skipped == ["count", "stddev"]


def test_a_cell_is_released_only_once(budget, cell):
    """Re-releasing would spend budget again and produce a second sample of the
    same private quantity (REVIEW section F1)."""
    from django.db import IntegrityError, transaction

    do_release(cell, "1.500000")

    with pytest.raises(IntegrityError), transaction.atomic():
        do_release(cell, "1.500000")


def test_a_published_release_cannot_be_edited(budget, cell):
    """Immutable snapshots. Editing a published value would falsify the record
    of what was disclosed."""
    outcome = do_release(cell)
    statistic = outcome.statistics[0]
    statistic.value = Decimal("1")

    with pytest.raises(NotImplementedError, match="immutable"):
        statistic.save()


def test_a_release_cannot_be_deleted_while_ledger_entries_point_at_it(budget, cell):
    """PROTECT. Deleting a release would orphan the spends that paid for it."""
    from django.db.models import ProtectedError

    outcome = do_release(cell)

    with pytest.raises((ProtectedError, NotImplementedError)):
        outcome.release.delete()


# --- tenancy -------------------------------------------------------------


def test_a_cross_collaboration_cell_is_refused_with_the_documented_exception(
    budget, cell, other_collaboration
):
    """Found in review of PR #2: the docstring promised CrossCollaborationSpend
    and the code raised ValueError.

    The type matters to callers, not just the message. A view catching
    CrossCollaborationSpend to render "this cell spans two groups" would have
    caught nothing, and the ValueError would have surfaced as a 500.
    """
    from budget.exceptions import CrossCollaborationSpend
    from collaborations.models import Cohort

    foreign_cohort = Cohort.objects.create(
        collaboration=other_collaboration, code="8610", name="Hospital sites"
    )

    with pytest.raises(CrossCollaborationSpend):
        release_benchmark(
            cohort=foreign_cohort,
            metric=cell["metric"],
            period=cell["period"],
            epsilon=Decimal("1.500000"),
        )

    assert BenchmarkRelease.objects.count() == 0
    assert LedgerEntry.objects.count() == 0


# --- a release reporting on its own usefulness ----------------------------


def _release_with(cohort, metric, period, values: dict[str, str]):
    """A release carrying exactly these statistic values.

    Constructed rather than produced by a real release, deliberately. The
    property under test is a function of the STORED values, and driving it
    through the mechanism would make the test depend on where the noise landed
    -- which is precisely the thing that varies. An earlier version did exactly
    that and was flaky: at N=8 even epsilon=3 inverts the quartiles often
    enough to fail.
    """
    release = BenchmarkRelease.objects.create(
        period=period,
        cohort=cohort,
        metric=metric,
        n_contributors=8,
        epsilon_spent=Decimal("1.000000"),
    )
    for statistic, value in values.items():
        ReleasedStatistic.objects.create(
            release=release,
            statistic=statistic,
            mechanism="exponential",
            value=Decimal(value),
            epsilon_spent=Decimal("0.333334"),
        )
    return release


def test_ordered_quantiles_are_recognised(cohort, metric, period):
    release = _release_with(
        cohort, metric, period, {"q25": "3000", "median": "3400", "q75": "3800"}
    )

    assert release.quantiles_are_ordered is True


def test_unordered_quantiles_are_detected(cohort, metric, period):
    """PRODUCT-CRITICAL, and observed for real.

    Each quantile is drawn independently by the exponential mechanism, so at
    small N or tight epsilon the noise can exceed the spacing between them and
    q75 can land below q25. Seen in the seeded demo at N=6: q25=131.8,
    q75=126.1 -- these are those numbers.

    Detecting it needs no access to the data. It is a property of the released
    values alone, and it is the most direct evidence a release carries about
    whether it can be relied on.
    """
    release = _release_with(
        cohort, metric, period, {"q25": "131.8", "median": "171.9", "q75": "126.1"}
    )

    assert release.quantiles_are_ordered is False


def test_a_release_with_too_few_quantiles_to_compare_reports_none(
    cohort, metric, period
):
    """Not ordered, not unordered -- unknowable. Returning False would flag a
    perfectly good single-statistic release as broken."""
    release = _release_with(cohort, metric, period, {"median": "3400"})

    assert release.quantiles_are_ordered is None


def test_unordered_quantiles_are_not_silently_reordered(budget, cell):
    """Sorting would be privacy-safe -- DP is closed under post-processing --
    but it would replace a visibly broken number with an invisibly meaningless
    one. The released values are stored exactly as the mechanism produced them.
    """
    outcome = do_release(cell, "1.500000")

    # Compare insertion order and 6-dp values. The in-memory objects keep the
    # mechanism's full precision while the column stores six places, so an
    # exact object-to-object comparison would fail on rounding rather than on
    # the reordering this test is about.
    stored = [
        (s.statistic, s.value.quantize(Decimal("0.000001")))
        for s in outcome.release.statistics.all().order_by("id")
    ]
    produced = [
        (s.statistic, s.value.quantize(Decimal("0.000001")))
        for s in outcome.statistics
    ]

    assert stored == produced
    assert [name for name, _ in stored] == ["q25", "median", "q75"], (
        "statistics were reordered on the way to the database"
    )
