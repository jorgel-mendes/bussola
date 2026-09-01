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

from budget.models import BudgetPeriod, LedgerEntry


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

    @admin.display(description="Spent")
    def epsilon_spent(self, obj: BudgetPeriod):
        return obj.spent()

    @admin.display(description="Remaining")
    def epsilon_remaining(self, obj: BudgetPeriod):
        return obj.remaining()


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
