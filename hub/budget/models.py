"""BudgetPeriod and the append-only LedgerEntry.

This is the accounting layer, and it is deliberately built *before* any
differential privacy exists in the tree (REVIEW section F4, retro action A1).
It is pure Django: if OpenDP fights us, the budget system still works and is
still auditable.

Two invariants live here, and both are privacy invariants rather than data
hygiene:

RULE 1 -- Append-only. A ledger entry is never updated and never deleted.
An epsilon spend that can be edited away is not an audit trail; the Auditor
actor (SPEC section 2) exists precisely to check that nothing was
over-released, and that check is worthless if history is mutable.

RULE 2 -- Positive spends only. A zero or negative entry would let a release
be recorded that charges nothing, or worse, credit budget back. Enforced by
CheckConstraint, at the database level, because an application check is not a
guarantee when rows can arrive via a fixture or a shell session.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.db.models import Sum

from budget.exceptions import UnsupportedAccountant


class Accountant(models.TextChoices):
    """How epsilon composes across the releases in one period.

    BASIC is shipped first on purpose (REVIEW section F1): epsilon simply adds,
    which an Auditor can verify with a calculator and which can be explained on
    camera in one sentence. zCDP gives materially better utility and is the
    obvious Sprint 3 upgrade, but an accountant you can explain beats one you
    cannot.
    """

    BASIC = "basic", "Basic composition (epsilon adds linearly)"
    ZCDP = "zcdp", "Zero-concentrated DP (not yet implemented)"


class BudgetPeriod(models.Model):
    """The privacy budget for one reporting period.

    One-to-one with ReportingPeriod, which is itself scoped to a collaboration
    -- so this is per (collaboration, period), the scope REVIEW section F
    specifies. A redundant collaboration FK is deliberately NOT carried here:
    it could drift out of agreement with ``period.collaboration`` and produce a
    budget that claims to belong to a group it does not. The collaboration is
    exposed as a property instead. See GLOSSARY naming rule 3.
    """

    period = models.OneToOneField(
        "ingest.ReportingPeriod", on_delete=models.CASCADE, related_name="budget"
    )
    epsilon_total = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=(
            "Total epsilon this collaboration may spend on this period, across "
            "all cohorts, metrics and statistics. Once it is gone, further "
            "releases are refused rather than served."
        ),
    )
    delta = models.DecimalField(
        max_digits=20,
        decimal_places=18,
        default=Decimal("0"),
        help_text=(
            "Reserved for approximate DP. Zero under pure epsilon-DP, which is "
            "what the quantile (exponential) mechanism provides."
        ),
    )
    accountant = models.CharField(
        max_length=16, choices=Accountant.choices, default=Accountant.BASIC
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period__starts"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(epsilon_total__gt=0),
                name="budget_epsilon_total_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(delta__gte=0),
                name="budget_delta_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.period.label} · ε={self.epsilon_total}"

    # --- derived -----------------------------------------------------------

    @property
    def collaboration(self):
        """The owning collaboration, via the period.

        Not a stored FK: see the class docstring.
        """
        return self.period.collaboration

    def check_accountant_supported(self) -> None:
        """Refuse to account a budget whose composition rule we do not implement."""
        if self.accountant != Accountant.BASIC:
            raise UnsupportedAccountant(
                f"Budget for {self.period.label} declares accountant "
                f"'{self.accountant}', but only '{Accountant.BASIC}' is implemented. "
                f"Accounting it as basic composition would report the wrong "
                f"remaining epsilon."
            )

    def spent(self) -> Decimal:
        """Total epsilon already spent against this period.

        Basic composition: epsilon adds. Reading it from the ledger rather than
        from a cached counter is deliberate -- the ledger is the record of
        truth, and a counter that can disagree with it is a second source of
        truth for the one number that must not be wrong.
        """
        self.check_accountant_supported()
        total = self.entries.aggregate(total=Sum("epsilon_spent"))["total"]
        return total if total is not None else Decimal("0")

    def remaining(self) -> Decimal:
        return self.epsilon_total - self.spent()

    def can_afford(self, epsilon: Decimal) -> bool:
        return self.remaining() >= epsilon


class LedgerEntryQuerySet(models.QuerySet):
    """Blocks the bulk mutation paths that bypass ``Model.save()``.

    ``QuerySet.update()`` and ``QuerySet.delete()`` issue SQL directly and never
    call ``save()`` or ``delete()`` on the instance, so overriding those on the
    model alone leaves the ledger editable through the ORM. Both are closed here.

    Honest limit, stated rather than glossed: this closes the *ORM* paths. Raw
    SQL against the table is not prevented. A database trigger would make the
    guarantee absolute and is recorded as follow-up work -- it is deliberately
    not claimed as delivered.
    """

    def update(self, **kwargs):
        raise NotImplementedError(
            "LedgerEntry is append-only: bulk update is not permitted. "
            "An epsilon spend that can be edited is not an audit trail."
        )

    def delete(self):
        raise NotImplementedError(
            "LedgerEntry is append-only: bulk delete is not permitted. "
            "Privacy already disclosed cannot be un-disclosed by deleting its record."
        )


class LedgerEntry(models.Model):
    """One epsilon spend. Append-only (RULE 1).

    Every release writes one entry per statistic released, inside the same
    transaction as the release itself. A release without an entry is
    unaccounted privacy loss -- the one genuinely serious bug in this system.
    """

    budget_period = models.ForeignKey(
        BudgetPeriod, on_delete=models.PROTECT, related_name="entries"
    )
    # The release FK lands with BenchmarkRelease on day 3 and will be NOT NULL,
    # deviating from SPEC section 5.4's null=True: a nullable release column
    # permits exactly the orphaned-spend state the invariant forbids.
    metric = models.ForeignKey(
        "catalog.MetricDefinition", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    cohort = models.ForeignKey(
        "collaborations.Cohort", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    statistic = models.CharField(max_length=16, help_text="e.g. q75")
    mechanism = models.CharField(max_length=32, help_text="e.g. exponential")
    epsilon_spent = models.DecimalField(max_digits=10, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LedgerEntryQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "ledger entries"
        constraints = [
            # RULE 2. A non-positive spend would let a release be recorded that
            # charges nothing, or credit budget back.
            models.CheckConstraint(
                condition=models.Q(epsilon_spent__gt=0),
                name="ledger_epsilon_spent_positive",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.cohort.code}·{self.metric.code}·{self.statistic} "
            f"ε={self.epsilon_spent} ({self.mechanism})"
        )

    def save(self, *args, **kwargs):
        """Insert only. RULE 1."""
        if self.pk is not None:
            raise NotImplementedError(
                "LedgerEntry is append-only: an existing entry cannot be modified. "
                "To correct the record, write a new entry; history is not rewritten."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Never. RULE 1."""
        raise NotImplementedError(
            "LedgerEntry is append-only: entries are never deleted. "
            "Privacy already disclosed cannot be un-disclosed by deleting its record."
        )
