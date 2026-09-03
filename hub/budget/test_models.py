"""Budget model tests.

These defend PRIVACY invariants, not data hygiene. The distinction matters for
whoever reads a failure here later: if one of these fails, the audit trail the
product's credibility rests on is not trustworthy, and the correct response is
to stop rather than to adjust the test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from budget.exceptions import UnsupportedAccountant
from budget.models import Accountant, BudgetPeriod, LedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def budget(period) -> BudgetPeriod:
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("1.0000"))


def make_release(budget, cohort, metric):
    from benchmarks.models import BenchmarkRelease

    existing = BenchmarkRelease.objects.filter(
        cohort=cohort, metric=metric, period=budget.period
    ).first()
    return existing or BenchmarkRelease.objects.create(
        period=budget.period,
        cohort=cohort,
        metric=metric,
        n_contributors=8,
        epsilon_spent=Decimal("1.000000"),
    )


def make_entry(budget, cohort, metric, epsilon="0.100000", statistic="median") -> LedgerEntry:
    return LedgerEntry.objects.create(
        budget_period=budget,
        release=make_release(budget, cohort, metric),
        cohort=cohort,
        metric=metric,
        statistic=statistic,
        mechanism="exponential",
        epsilon_spent=Decimal(epsilon),
    )


# --- BudgetPeriod ---------------------------------------------------------


def test_budget_is_scoped_to_a_collaboration_through_its_period(budget, collaboration):
    """The budget scope is (collaboration, period).

    Carried through the period rather than duplicated as an FK, so the two can
    never disagree about which group's epsilon this is.
    """
    assert budget.collaboration == collaboration


def test_a_period_can_have_only_one_budget(period, budget):
    """Two budgets for one period would be two answers to 'how much is left'."""
    with pytest.raises(IntegrityError), transaction.atomic():
        BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("5.0"))


def test_epsilon_total_must_be_positive_at_db_level(period):
    """A zero or negative budget is not a budget. Enforced by CheckConstraint
    rather than clean(), because a fixture or shell session bypasses clean()."""
    with pytest.raises(IntegrityError), transaction.atomic():
        BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("0"))


def test_spent_is_zero_before_any_release(budget):
    assert budget.spent() == Decimal("0")
    assert budget.remaining() == Decimal("1.0000")


def test_spent_sums_the_ledger_under_basic_composition(budget, cohort, metric):
    """Basic composition: epsilon adds. This is the arithmetic an Auditor can
    check with a calculator, which is why it ships before zCDP."""
    make_entry(budget, cohort, metric, "0.100000", "q25")
    make_entry(budget, cohort, metric, "0.250000", "median")

    assert budget.spent() == Decimal("0.350000")
    assert budget.remaining() == Decimal("0.650000")


def test_spent_reads_the_ledger_rather_than_a_cached_counter(budget, cohort, metric):
    """The ledger is the single record of truth.

    A cached total that can drift from the entries would be a second source of
    truth for the one number that must not be wrong.
    """
    make_entry(budget, cohort, metric, "0.400000")
    assert budget.spent() == Decimal("0.400000")

    make_entry(budget, cohort, metric, "0.100000")
    assert budget.spent() == Decimal("0.500000")


def test_an_unimplemented_accountant_raises_rather_than_falling_back(period):
    """A zCDP budget accounted as basic would report the wrong remaining epsilon.

    Refusing loudly beats a plausible wrong number -- the defect class Sprint 1
    shipped three of.
    """
    zcdp = BudgetPeriod.objects.create(
        period=period, epsilon_total=Decimal("1.0"), accountant=Accountant.ZCDP
    )
    with pytest.raises(UnsupportedAccountant):
        zcdp.spent()


# --- LedgerEntry: RULE 1, append-only -------------------------------------


def test_an_entry_cannot_be_modified(budget, cohort, metric):
    """RULE 1. An epsilon spend that can be edited is not an audit trail."""
    entry = make_entry(budget, cohort, metric, "0.100000")
    entry.epsilon_spent = Decimal("0.000001")

    with pytest.raises(NotImplementedError, match="append-only"):
        entry.save()

    entry.refresh_from_db()
    assert entry.epsilon_spent == Decimal("0.100000")


def test_an_entry_cannot_be_deleted(budget, cohort, metric):
    """RULE 1. Privacy already disclosed cannot be un-disclosed."""
    entry = make_entry(budget, cohort, metric)

    with pytest.raises(NotImplementedError, match="append-only"):
        entry.delete()

    assert LedgerEntry.objects.filter(pk=entry.pk).exists()


def test_bulk_update_is_blocked(budget, cohort, metric):
    """queryset.update() never calls save(), so overriding save() alone would
    leave the ledger editable through the ORM. Closed on the QuerySet."""
    make_entry(budget, cohort, metric)

    with pytest.raises(NotImplementedError, match="append-only"):
        LedgerEntry.objects.all().update(epsilon_spent=Decimal("0.000001"))

    assert budget.spent() == Decimal("0.100000")


def test_bulk_delete_is_blocked(budget, cohort, metric):
    """Same hole, other verb."""
    make_entry(budget, cohort, metric)

    with pytest.raises(NotImplementedError, match="append-only"):
        LedgerEntry.objects.all().delete()

    assert LedgerEntry.objects.count() == 1


def test_the_budget_period_cannot_be_deleted_out_from_under_its_entries(
    budget, cohort, metric
):
    """on_delete=PROTECT. Cascading here would delete the audit trail as a side
    effect of tidying a budget."""
    make_entry(budget, cohort, metric)

    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        budget.delete()


# --- LedgerEntry: RULE 2, positive spends only ----------------------------


def test_a_zero_spend_is_rejected_at_db_level(budget, cohort, metric):
    """A zero-cost entry would record a release that charged nothing."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_entry(budget, cohort, metric, "0")


def test_a_negative_spend_is_rejected_at_db_level(budget, cohort, metric):
    """A negative entry would credit privacy budget back. There is no such
    operation: disclosure is not reversible."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_entry(budget, cohort, metric, "-0.500000")


# --- admin: the affordance is part of the control -------------------------


def test_the_admin_offers_no_way_to_add_change_or_delete_a_ledger_entry():
    """The model guards raise, but only after an auditor has clicked a button
    that appeared to work. Removing the affordance is part of the control."""
    from django.contrib import admin as django_admin

    from budget.admin import LedgerEntryAdmin

    site_admin = django_admin.site._registry[LedgerEntry]
    assert isinstance(site_admin, LedgerEntryAdmin)
    assert site_admin.has_add_permission(None) is False
    assert site_admin.has_change_permission(None) is False
    assert site_admin.has_delete_permission(None) is False


def test_every_ledger_field_is_read_only_in_the_admin():
    from django.contrib import admin as django_admin

    site_admin = django_admin.site._registry[LedgerEntry]
    readonly = set(site_admin.get_readonly_fields(None))
    assert {"epsilon_spent", "statistic", "mechanism", "created_at"} <= readonly


def test_the_admin_does_not_error_on_an_unimplemented_accountant(period):
    """Found in review of PR #1.

    zCDP is a selectable choice, and spent()/remaining() raise for it, so the
    changelist would 500 the moment anyone picked it. The raise stays -- a zCDP
    budget reported as if composition were linear would be a plausible wrong
    number, worse than a visible gap -- but the admin degrades to a marker.
    """
    from django.contrib import admin as django_admin

    zcdp = BudgetPeriod.objects.create(
        period=period, epsilon_total=Decimal("1.0"), accountant=Accountant.ZCDP
    )
    site_admin = django_admin.site._registry[BudgetPeriod]

    assert "not implemented" in str(site_admin.epsilon_spent(zcdp))
    assert "not implemented" in str(site_admin.epsilon_remaining(zcdp))


def test_the_admin_still_reports_real_figures_for_a_supported_accountant(
    budget, cohort, metric
):
    """The degradation must not swallow the normal case."""
    from django.contrib import admin as django_admin

    make_entry(budget, cohort, metric, "0.250000")
    site_admin = django_admin.site._registry[BudgetPeriod]

    assert site_admin.epsilon_spent(budget) == Decimal("0.250000")
    assert site_admin.epsilon_remaining(budget) == Decimal("0.750000")
