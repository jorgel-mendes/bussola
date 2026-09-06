"""Ledger export tests (S3-4).

The failure this file exists to prevent is not a crash. It is an export that
looks complete and is not -- a stray slice, a filter, a paginator -- handed to
an auditor who signs it off. A missing row in an audit record is worse than a
missing file, because a missing file gets noticed.

Retro action B3: each of these was verified by planting the defect it guards.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory

from budget.admin import BudgetPeriodAdmin, LedgerEntryAdmin
from budget.export import COLUMNS, ledger_rows, write_ledger_csv
from budget.models import BudgetPeriod, LedgerEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def budget(period) -> BudgetPeriod:
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("1.0000"))


@pytest.fixture
def entries(budget, release, cohort, metric):
    """Three spends, in ledger order, totalling 0.6."""
    return [
        LedgerEntry.objects.create(
            budget_period=budget,
            release=release,
            cohort=cohort,
            metric=metric,
            statistic=statistic,
            mechanism="exponential",
            epsilon_spent=Decimal("0.200000"),
        )
        for statistic in ("q25", "median", "q75")
    ]


def _ordered(budget):
    return budget.entries.select_related(
        "budget_period__period__collaboration", "cohort", "metric"
    ).order_by("created_at", "id")


# --- the cumulative column --------------------------------------------------


def test_cumulative_epsilon_is_a_running_total(budget, entries):
    """The column that makes basic composition visible in a spreadsheet."""
    rows = list(ledger_rows(_ordered(budget)))

    assert [r["cumulative_epsilon"] for r in rows] == [
        Decimal("0.200000"),
        Decimal("0.400000"),
        Decimal("0.600000"),
    ]


def test_the_final_cumulative_equals_what_the_budget_says_was_spent(budget, entries):
    """The auditor's reconciliation, asserted.

    Two independent paths to the same number: the export sums row by row, and
    BudgetPeriod.spent() aggregates in SQL. They must agree, or one of them is
    telling the auditor something false.
    """
    rows = list(ledger_rows(_ordered(budget)))

    assert rows[-1]["cumulative_epsilon"] == budget.spent() == Decimal("0.600000")


def test_cumulative_is_monotone(budget, entries):
    """Guaranteed by RULE 2 -- spends are positive -- and checked here because
    the whole point of the column is that a reader can trust it to only rise."""
    totals = [r["cumulative_epsilon"] for r in ledger_rows(_ordered(budget))]

    assert all(a < b for a, b in zip(totals, totals[1:], strict=False))


def test_budget_exceeded_is_false_throughout_a_healthy_ledger(budget, entries):
    assert not any(r["budget_exceeded"] for r in ledger_rows(_ordered(budget)))


def test_budget_exceeded_flags_the_row_where_the_total_is_passed(budget, entries):
    """It should never fire. If it ever does, the auditor must see WHICH row.

    Simulated by exporting against a smaller authorised total rather than by
    writing an over-spend, because the accountant refuses to write one -- which
    is the point. The column exists to make an impossible state visible if the
    guard that makes it impossible ever fails.
    """
    rows = list(ledger_rows(_ordered(budget), budget_total=Decimal("0.5")))

    assert [r["budget_exceeded"] for r in rows] == [False, False, True]


# --- completeness -----------------------------------------------------------


def test_every_ledger_entry_reaches_the_csv(budget, entries):
    """The failure that matters: a short export that still looks complete."""
    fh = io.StringIO()
    written = write_ledger_csv(_ordered(budget), fh, budget_total=budget.epsilon_total)

    fh.seek(0)
    rows = list(csv.DictReader(fh))
    assert written == len(rows) == budget.entries.count() == 3


def test_csv_carries_the_declared_columns_in_order(budget, entries):
    """Auditors index these by position in scripts and spreadsheets."""
    fh = io.StringIO()
    write_ledger_csv(_ordered(budget), fh)

    fh.seek(0)
    assert next(csv.reader(fh)) == COLUMNS


def test_export_carries_no_released_values(budget, entries):
    """The ledger records what privacy COST, never what was disclosed.

    An export that leaked released statistics would turn the audit trail into a
    second publication channel -- one with no suppression check and no budget.
    """
    fh = io.StringIO()
    write_ledger_csv(_ordered(budget), fh)

    assert "value" not in [c.lower() for c in COLUMNS]
    assert not any(hasattr(e, "value") for e in entries)


# --- the management command -------------------------------------------------


def test_command_writes_a_reconciled_file(budget, entries, collaboration, period, tmp_path):
    out = tmp_path / "ledger.csv"
    stdout = io.StringIO()
    call_command(
        "export_ledger",
        collaboration=collaboration.slug,
        period=period.label,
        out=out,
        stdout=stdout,
    )

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 3
    assert "Reconciles" in stdout.getvalue()
    assert str(budget.spent()) in stdout.getvalue()


def test_command_refuses_a_period_with_no_budget(collaboration, period):
    """No budget means nothing was ever released, and an empty CSV would read
    as 'audited, nothing found' rather than 'there was nothing to audit'."""
    with pytest.raises(CommandError, match="no budget"):
        call_command("export_ledger", collaboration=collaboration.slug, period=period.label)


def test_command_refuses_an_unknown_period(collaboration):
    with pytest.raises(CommandError, match="has no period"):
        call_command("export_ledger", collaboration=collaboration.slug, period="1999-01")


def test_command_scopes_to_the_named_collaboration(
    budget, entries, collaboration, period, other_collaboration
):
    """Tenancy. Retro action B1: the weak claim is that two collaborations are
    independent; the claim asserted here is that a mismatched pair is REFUSED.
    """
    with pytest.raises(CommandError, match="has no period"):
        call_command(
            "export_ledger", collaboration=other_collaboration.slug, period=period.label
        )


# --- the admin console, which is where the Auditor actually is --------------
#
# SPEC section 4 gives the Auditor the Django admin rather than a bespoke UI --
# roughly two weeks not spent building CRUD (ADR-0001). That makes the admin
# action a shipped feature, not scaffolding, and it is tested as one.


def _admin_request():
    request = RequestFactory().post("/admin/budget/budgetperiod/")
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_period_action_exports_every_entry_as_an_attachment(budget, entries):
    admin_instance = BudgetPeriodAdmin(BudgetPeriod, AdminSite())
    response = admin_instance.export_ledger_csv(
        _admin_request(), BudgetPeriod.objects.filter(pk=budget.pk)
    )

    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    body = response.content.decode()
    assert body.count("\r\n") == 4  # header + 3 entries
    assert "bussola-ledger-" in response["Content-Disposition"]


def test_period_action_refuses_more_than_one_period(budget, entries, other_collaboration):
    """A merged file would carry a cumulative total spanning separate budgets.

    That number is not merely unhelpful, it is wrong in a way that reads as
    right: it would show one collaboration's spend accumulating into another's
    authorised total.
    """
    from ingest.models import ReportingPeriod

    other_period = ReportingPeriod.objects.create(
        collaboration=other_collaboration,
        label="2026-08",
        starts=budget.period.starts,
        ends=budget.period.ends,
    )
    BudgetPeriod.objects.create(period=other_period, epsilon_total=Decimal("1.0000"))

    admin_instance = BudgetPeriodAdmin(BudgetPeriod, AdminSite())
    response = admin_instance.export_ledger_csv(_admin_request(), BudgetPeriod.objects.all())

    assert response is None


def test_ledger_action_exports_the_selection(budget, entries):
    admin_instance = LedgerEntryAdmin(LedgerEntry, AdminSite())
    selection = LedgerEntry.objects.filter(pk__in=[entries[0].pk, entries[1].pk])
    response = admin_instance.export_selected_csv(_admin_request(), selection)

    assert response.content.decode().count("\r\n") == 3  # header + 2 entries


def test_the_ledger_admin_offers_no_way_to_edit_what_it_exports(budget, entries):
    """The export must not become the affordance that reintroduces mutation."""
    admin_instance = LedgerEntryAdmin(LedgerEntry, AdminSite())

    assert admin_instance.has_add_permission(_admin_request()) is False
    assert admin_instance.has_change_permission(_admin_request()) is False
    assert admin_instance.has_delete_permission(_admin_request()) is False
