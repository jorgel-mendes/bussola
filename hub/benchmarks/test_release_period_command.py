"""Tests for `manage.py release_period` — retro action B2.

This command had **zero** test coverage at the end of Sprint 2. The Sprint 2
review called the operational surface "partially" tested; it was not tested at
all, and this file is the correction.

It matters more than the coverage number suggests. `release_period` is the only
thing in the system that SPENDS PRIVACY BUDGET, and epsilon once spent cannot be
refunded. Every behaviour asserted here is one where getting it wrong means
either a disclosure nobody was charged for, or a charge for a disclosure nobody
received.

The tests deliberately use small cohorts and few cells: each release runs OpenDP
three times at roughly 450ms, so a careless fixture here would add minutes to
every push.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from benchmarks.models import BenchmarkRelease
from budget.models import BudgetPeriod, LedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def budget(period):
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("6.0000"))


@pytest.fixture
def cohort_with_submissions(cohort, metric, period, make_contributors):
    """Enough contributors to clear the suppression threshold."""
    make_contributors(metric, period, ["3000", "3100", "3200", "3300", "3400", "3500"])
    return cohort


@pytest.fixture
def second_cohort_with_submissions(collaboration, metric, period):
    """A SECOND releasable cell, so the budget can actually run out.

    The shared fixtures give one cohort and one metric — a single cell, which
    can never exhaust a budget no matter how small it is. Exhaustion is the
    behaviour this command exists to get right, so it needs two.
    """
    from collaborations.models import Cohort
    from contributors.models import Contributor
    from ingest.models import Submission

    cohort = Cohort.objects.create(
        collaboration=collaboration, code="2011", name="Basic industrial chemicals"
    )
    for i, value in enumerate(["3050", "3150", "3250", "3350", "3450", "3550"], start=1):
        contributor = Contributor.objects.create(
            collaboration=collaboration, name=f"Second Plant {i:02d}", cohort=cohort
        )
        Submission.objects.create(
            contributor=contributor, period=period, metric=metric,
            value=Decimal(value), n_records=30, agent_version="test",
        )
    return cohort


def run(collaboration, period, epsilon="1.0", **kwargs):
    out = io.StringIO()
    call_command(
        "release_period",
        collaboration=collaboration.slug,
        period=period.label,
        epsilon=Decimal(epsilon),
        stdout=out,
        **kwargs,
    )
    return out.getvalue()


# --- the one that must never regress ---------------------------------------


def test_dry_run_spends_nothing_and_writes_nothing(
    collaboration, period, budget, cohort_with_submissions
):
    """The operator's safety net, and the reason it exists.

    Epsilon once spent cannot be refunded, so the preview must be free. A
    dry-run that charged anything would be worse than no dry-run at all,
    because the operator would use it believing the opposite.
    """
    output = run(collaboration, period, dry_run=True)

    assert BenchmarkRelease.objects.count() == 0
    assert LedgerEntry.objects.count() == 0
    assert budget.remaining() == Decimal("6.0000")
    assert "no budget spent" in output.lower()


def test_dry_run_reports_what_it_would_and_would_not_release(
    collaboration, period, budget, cohort_with_submissions
):
    """A statistic the build cannot release must be visible in the preview.

    Silently omitting it would leave the operator believing they had published
    something they had not.
    """
    output = run(collaboration, period, dry_run=True)

    assert "would release" in output
    assert "median" in output
    # The seeded metric lists `count`, which no mechanism is registered for.
    assert "skipping" in output


# --- spending, and stopping ------------------------------------------------


def test_a_release_charges_the_ledger_in_the_same_breath(
    collaboration, period, budget, cohort_with_submissions
):
    output = run(collaboration, period)

    release = BenchmarkRelease.objects.get()
    assert release.n_contributors == 6
    assert LedgerEntry.objects.filter(release=release).count() == 3
    assert budget.remaining() < Decimal("6.0000")
    assert "released" in output


def test_a_suppressed_cell_costs_nothing(collaboration, period, budget, cohort, metric):
    """Below the threshold, before any budget is touched.

    Charging for a cell that is then refused would drain a budget through cells
    that were never published — the operator pays for silence.
    """
    output = run(collaboration, period)

    assert "suppressed" in output
    assert LedgerEntry.objects.count() == 0
    assert budget.remaining() == Decimal("6.0000")


def test_an_exhausted_budget_stops_and_keeps_what_was_already_published(
    collaboration, period, cohort_with_submissions, second_cohort_with_submissions
):
    """Each cell is its own transaction, and that is load-bearing.

    A cell that cannot be paid for must not undo cells already published: those
    are real disclosures, and the ledger has to keep them. Rolling them back
    would erase the record of privacy that has already left the building.
    """
    BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("1.2"))

    output = run(collaboration, period, epsilon="1.0")

    assert "REFUSED" in output
    # The first cell was paid for and stays; the second could not be.
    assert BenchmarkRelease.objects.count() == 1
    assert LedgerEntry.objects.count() == 3


def test_the_refusal_reports_budget_remaining_after_the_rollback(
    collaboration, period, cohort_with_submissions, second_cohort_with_submissions
):
    """The subtle one, and the reason the command re-reads the budget.

    `BudgetExhausted.remaining` was measured INSIDE the transaction that then
    rolled back — after some of the cell's statistics had already been charged.
    Reporting that figure would tell the operator they have LESS budget than
    they do, and an operator who believes the budget is gone stops releasing.

    THE BUDGET HERE IS CHOSEN SO THE SECOND CELL FAILS PART-WAY THROUGH, and
    that is the whole test. The first version used 1.2, which leaves 0.199998 —
    less than one statistic's 0.333334 — so the second cell was refused on its
    FIRST spend, nothing was charged, and the two figures coincided. The test
    passed while the defect it names was plantable and undetected.

    1.5 leaves 0.499998: enough for one statistic of three. The cell charges
    0.333334, fails on the second, and rolls back — so `exc.remaining` reads
    0.166664 while the truth after rollback is 0.499998. Three times more
    budget than the operator would have been told they had.
    """
    budget = BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("1.5"))

    output = run(collaboration, period, epsilon="1.0")

    actual = budget.remaining()
    assert f"Actually remaining after rollback: {actual}" in output
    # The partial charge really was returned: a whole statistic's worth of
    # budget is back, not consumed by the cell that was refused.
    assert actual > Decimal("0.333334")


def test_already_published_cells_are_not_released_twice(
    collaboration, period, budget, cohort_with_submissions
):
    """Re-releasing would spend budget again and publish a DIFFERENT number for
    the same cell, because the mechanism is random. Releases are immutable
    snapshots precisely so that cannot happen."""
    run(collaboration, period)
    spent_after_first = budget.spent()

    output = run(collaboration, period)

    assert "1 already published" in output
    assert budget.spent() == spent_after_first


def test_nothing_to_do_is_said_rather_than_implied(
    collaboration, period, budget, cohort_with_submissions
):
    """A second run with every cell published must say so, not exit silently.

    An operator who sees no output cannot tell "already done" from "failed to
    find anything", and the second reading invites a re-run that would spend
    budget for a duplicate release.
    """
    run(collaboration, period)

    output = run(collaboration, period)

    assert "Nothing to do" in output


# --- refusals --------------------------------------------------------------


def test_a_non_positive_epsilon_is_refused(collaboration, period, budget):
    """Zero epsilon would publish a value while charging nothing for it."""
    with pytest.raises(CommandError, match="must be positive"):
        run(collaboration, period, epsilon="0")


def test_an_unknown_collaboration_is_refused(collaboration, period, budget):
    out = io.StringIO()
    with pytest.raises(CommandError, match="No active collaboration"):
        call_command(
            "release_period", collaboration="not-a-real-slug",
            period=period.label, epsilon=Decimal("1.0"), stdout=out,
        )


def test_an_unknown_period_is_refused(collaboration, period, budget):
    out = io.StringIO()
    with pytest.raises(CommandError, match="has no period"):
        call_command(
            "release_period", collaboration=collaboration.slug,
            period="1999-01", epsilon=Decimal("1.0"), stdout=out,
        )


def test_a_period_with_no_budget_is_refused(collaboration, period):
    """Releasing without a budget would be an unaccounted disclosure — the one
    genuinely serious bug in this system."""
    with pytest.raises(Exception) as exc:
        run(collaboration, period)

    assert "budget" in str(exc.value).lower()
