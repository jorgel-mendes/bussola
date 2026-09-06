"""Admin for the privacy budget and the epsilon ledger.

This is the Auditor's console (SPEC section 2) and the Analyst's. Django admin
gives it to us for free, which is roughly two weeks not spent building CRUD --
the reason there is no bespoke admin UI anywhere in the backlog (ADR-0001).

The ledger is registered READ-ONLY. Django admin would otherwise render add,
change and delete controls over an append-only table: the model guards would
still raise, but only after an auditor had been shown a delete button that
appears to work. Removing the affordance is part of the control, not decoration.
"""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpResponse

from budget.exceptions import UnsupportedAccountant
from budget.export import export_filename, write_ledger_csv
from budget.models import BudgetPeriod, LedgerEntry


def _csv_response(filename: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class LedgerEntryInline(admin.TabularInline):
    """Every spend against this budget, in order, read-only."""

    model = LedgerEntry
    extra = 0
    can_delete = False
    fields = ["created_at", "cohort", "metric", "statistic", "mechanism", "epsilon_spent"]
    readonly_fields = fields
    ordering = ["created_at"]

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(BudgetPeriod)
class BudgetPeriodAdmin(admin.ModelAdmin):
    list_display = ["period", "collaboration_name", "epsilon_total", "epsilon_spent", "epsilon_remaining", "accountant"]
    list_filter = ["accountant", "period__collaboration"]
    inlines = [LedgerEntryInline]
    fieldsets = [
        (None, {"fields": ["period", "accountant"]}),
        (
            "Privacy budget",
            {
                "fields": ["epsilon_total", "delta"],
                "description": (
                    "<strong>Total epsilon for this period, across every cohort, "
                    "metric and statistic.</strong> When it is gone, further releases "
                    "are refused rather than served — the system declines rather than "
                    "leaking. Basic composition means epsilon adds linearly, so this "
                    "figure can be checked against the ledger with a calculator."
                ),
            },
        ),
    ]

    @admin.display(description="Collaboration")
    def collaboration_name(self, obj: BudgetPeriod) -> str:
        return obj.collaboration.name

    # spent()/remaining() raise UnsupportedAccountant for a non-basic budget,
    # and zCDP is a selectable choice -- so without this the changelist 500s the
    # moment anyone picks it. Found in review of PR #1.
    #
    # The raise itself is kept: reporting a zCDP budget's remaining epsilon as
    # if composition were linear would be a plausible wrong number, which is
    # worse than a visible gap. The admin degrades to a marker instead.
    @admin.display(description="Spent")
    def epsilon_spent(self, obj: BudgetPeriod):
        try:
            return obj.spent()
        except UnsupportedAccountant:
            return "— (accountant not implemented)"

    @admin.display(description="Remaining")
    def epsilon_remaining(self, obj: BudgetPeriod):
        try:
            return obj.remaining()
        except UnsupportedAccountant:
            return "— (accountant not implemented)"

    # S3-4. One period, one file, every entry -- which is the unit an auditor
    # actually reviews. Exporting a hand-picked selection is offered on the
    # ledger changelist instead, and is deliberately labelled as a selection.
    @admin.action(description="Export this period's full ledger as CSV")
    def export_ledger_csv(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one period. A single file merging several periods "
                "would carry a cumulative total that spans separate budgets, which "
                "is not a number that means anything.",
                level="error",
            )
            return None

        budget = queryset.get()
        entries = budget.entries.select_related(
            "budget_period__period__collaboration", "cohort", "metric"
        ).order_by("created_at", "id")

        response = _csv_response(
            export_filename(
                collaboration_slug=budget.period.collaboration.slug,
                period_label=budget.period.label,
            )
        )
        write_ledger_csv(entries, response, budget_total=budget.epsilon_total)
        return response

    actions = ["export_ledger_csv"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Append-only: no add, no change, no delete. See the module docstring."""

    list_display = ["created_at", "budget_period", "cohort", "metric", "statistic", "mechanism", "epsilon_spent"]
    list_filter = ["mechanism", "statistic", "budget_period__period__collaboration"]
    search_fields = ["metric__code", "cohort__code", "statistic"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    # S3-4. A SELECTION, and the name says so. The cumulative column on a
    # filtered subset is the running total of what was selected, not of the
    # period -- an auditor reconciling against a budget wants the period export
    # on BudgetPeriod, and calling this one "full ledger" would invite exactly
    # that mistake.
    @admin.action(description="Export selected entries as CSV")
    def export_selected_csv(self, request, queryset):
        entries = queryset.select_related(
            "budget_period__period__collaboration", "cohort", "metric"
        ).order_by("created_at", "id")

        response = _csv_response("bussola-ledger-selection.csv")
        write_ledger_csv(entries, response)
        return response

    actions = ["export_selected_csv"]
