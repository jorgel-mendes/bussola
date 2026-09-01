"""Accountant tests.

The sequential cases live here. The concurrency case -- K parallel releases
against a budget affording K-1 -- is the flagship test and lives in
``test_concurrency.py``, because it needs real threads, a real transactional
database, and must refuse to pass vacuously on SQLite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from budget.accountant import budget_for, spend
from budget.exceptions import BudgetExhausted, BudgetNotConfigured, UnsupportedAccountant
from budget.models import Accountant, BudgetPeriod, LedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def budget(period) -> BudgetPeriod:
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("1.0000"))


def charge(budget, cohort, metric, epsilon, statistic="median") -> LedgerEntry:
    return spend(
        budget_period=budget,
        cohort=cohort,
        metric=metric,
        statistic=statistic,
        mechanism="exponential",
        epsilon=Decimal(epsilon),
    )


# --- the happy path -------------------------------------------------------


def test_a_spend_writes_one_ledger_entry(budget, cohort, metric):
    entry = charge(budget, cohort, metric, "0.250000", statistic="q75")

    assert entry.pk is not None
    assert entry.epsilon_spent == Decimal("0.250000")
    assert entry.statistic == "q75"
    assert entry.mechanism == "exponential"
    assert budget.spent() == Decimal("0.250000")


def test_spends_accumulate_across_statistics(budget, cohort, metric):
    """A release of q25/median/q75 is three queries and three entries.

    The ledger records each statistic separately rather than one lump per
    release, so an Auditor can see what each unit of epsilon bought.
    """
    charge(budget, cohort, metric, "0.100000", "q25")
    charge(budget, cohort, metric, "0.100000", "median")
    charge(budget, cohort, metric, "0.100000", "q75")

    assert LedgerEntry.objects.count() == 3
    assert budget.spent() == Decimal("0.300000")


def test_the_full_budget_can_be_spent_exactly(budget, cohort, metric):
    """Boundary: spending exactly the remaining epsilon is permitted.

    Off-by-one here would either refuse a legitimate release or, worse, allow
    one epsilon past the limit.
    """
    charge(budget, cohort, metric, "1.000000")

    assert budget.remaining() == Decimal("0")


# --- refusal --------------------------------------------------------------


def test_a_release_exceeding_the_budget_is_refused(budget, cohort, metric):
    """The designed behaviour: the system declines rather than leaking."""
    with pytest.raises(BudgetExhausted) as exc:
        charge(budget, cohort, metric, "1.500000")

    assert exc.value.requested == Decimal("1.500000")
    assert exc.value.remaining == Decimal("1.0000")


def test_a_refused_release_writes_nothing(budget, cohort, metric):
    """A refusal must leave no trace in the ledger.

    If a refused release still wrote an entry, the budget would be drawn down
    by releases that never happened -- and the ledger would misreport what was
    actually disclosed.
    """
    charge(budget, cohort, metric, "0.900000")

    with pytest.raises(BudgetExhausted):
        charge(budget, cohort, metric, "0.500000")

    assert LedgerEntry.objects.count() == 1
    assert budget.spent() == Decimal("0.900000")


def test_refusal_reports_how_much_is_actually_left(budget, cohort, metric):
    """The operator is told the number, not merely that something failed."""
    charge(budget, cohort, metric, "0.700000")

    with pytest.raises(BudgetExhausted) as exc:
        charge(budget, cohort, metric, "0.400000")

    assert exc.value.remaining == Decimal("0.300000")


def test_epsilon_just_over_the_remaining_budget_is_refused(budget, cohort, metric):
    """The boundary from the other side, at six decimal places.

    Decimal, not float: 0.1 + 0.2 > 0.3 is true in binary floating point, and a
    budget check that rounds in the wrong direction is a silent over-release.
    """
    charge(budget, cohort, metric, "0.999999")

    with pytest.raises(BudgetExhausted):
        charge(budget, cohort, metric, "0.000002")

    charge(budget, cohort, metric, "0.000001")
    assert budget.remaining() == Decimal("0")


# --- misuse ---------------------------------------------------------------


def test_a_non_positive_spend_is_refused_before_touching_the_ledger(budget, cohort, metric):
    with pytest.raises(ValueError, match="non-positive"):
        charge(budget, cohort, metric, "0")

    assert LedgerEntry.objects.count() == 0


def test_a_period_without_a_budget_raises_rather_than_defaulting(period):
    """Defaulting would let a period spend privacy nobody authorised."""
    with pytest.raises(BudgetNotConfigured, match=period.label):
        budget_for(period)


def test_budget_for_returns_the_configured_budget(period, budget):
    assert budget_for(period) == budget


def test_an_unimplemented_accountant_refuses_to_spend(period, cohort, metric):
    """Fail loudly rather than account zCDP as if it were basic."""
    zcdp = BudgetPeriod.objects.create(
        period=period, epsilon_total=Decimal("1.0"), accountant=Accountant.ZCDP
    )
    with pytest.raises(UnsupportedAccountant):
        charge(zcdp, cohort, metric, "0.100000")

    assert LedgerEntry.objects.count() == 0


# --- tenancy --------------------------------------------------------------


def test_budgets_of_separate_collaborations_are_independent(
    period, budget, cohort, metric, other_collaboration
):
    """Two unrelated groups must never draw down each other's epsilon.

    This is the budget half of the tenancy boundary (ADR-0004). Spending one
    collaboration's budget to exhaustion must leave the other's untouched.
    """
    from datetime import date

    from ingest.models import ReportingPeriod

    other_period = ReportingPeriod.objects.create(
        collaboration=other_collaboration,
        label="2026-07",
        starts=date(2026, 7, 1),
        ends=date(2026, 8, 1),
    )
    other_budget = BudgetPeriod.objects.create(
        period=other_period, epsilon_total=Decimal("1.0000")
    )

    charge(budget, cohort, metric, "1.000000")

    assert budget.remaining() == Decimal("0")
    assert other_budget.remaining() == Decimal("1.0000")
    assert other_budget.spent() == Decimal("0")


# --- rollback semantics ---------------------------------------------------
#
# These exist because a planted defect -- writing the ledger entry BEFORE the
# budget check -- did not fail `test_a_refused_release_writes_nothing`. That
# test passes because @transaction.atomic rolls the entry back, not because of
# statement ordering. The rollback is therefore load-bearing, and load-bearing
# behaviour gets its own tests.
#
# It matters most under nesting: from day 3 the release path calls spend()
# inside its own atomic block, so a refusal must roll back to a savepoint
# without destroying the work that already succeeded in the outer block.


def test_a_refusal_rolls_back_to_a_savepoint_inside_an_outer_transaction(
    budget, cohort, metric
):
    """The release path's exact shape: spend() nested in an outer atomic block.

    A refused statistic must undo only itself. If the nested atomic did not
    create a savepoint, the caught exception would leave the outer transaction
    broken and the successful spend would be lost -- or, worse, the refused one
    would survive.
    """
    from django.db import transaction

    with transaction.atomic():
        charge(budget, cohort, metric, "0.900000", "q25")

        with pytest.raises(BudgetExhausted):
            charge(budget, cohort, metric, "0.500000", "median")

    assert LedgerEntry.objects.count() == 1
    assert LedgerEntry.objects.get().statistic == "q25"
    assert budget.spent() == Decimal("0.900000")


def test_an_outer_rollback_discards_a_successful_spend(budget, cohort, metric):
    """The invariant's other direction, and the reason constraint 5 works.

    If the release fails after the ledger entry is written, the entry must go
    with it. A ledger entry for a release that does not exist is a phantom
    spend: it draws down the budget for a statistic nobody ever received.
    """
    from django.db import transaction

    class ReleaseFailed(Exception):
        pass

    with pytest.raises(ReleaseFailed), transaction.atomic():
        charge(budget, cohort, metric, "0.300000")
        raise ReleaseFailed("mechanism blew up after the ledger was written")

    assert LedgerEntry.objects.count() == 0
    assert budget.spent() == Decimal("0")
