"""Published releases: immutable snapshots of what was disclosed.

A release is a historical fact, not a view. Once published it is never
recomputed and never edited, for a reason that is specific to differential
privacy rather than general good practice: re-running a mechanism on the same
data spends the budget again AND produces a different number. An observer who
saw both outputs would hold two independent samples of the same private
quantity, which is strictly more information than either alone -- and the
second sample would be unaccounted unless it were charged again.

So the models here are append-only in the same way `budget.LedgerEntry` is, and
`(cohort, metric, period)` is unique: a cell is released once.
"""

from __future__ import annotations

from django.db import models


class AppendOnlyQuerySet(models.QuerySet):
    """Blocks the bulk mutation paths that bypass ``Model.save()``."""

    def update(self, **kwargs):
        raise NotImplementedError(
            "Published releases are immutable: bulk update is not permitted. "
            "A released statistic that can be edited is not a record of what "
            "was disclosed."
        )

    def delete(self):
        raise NotImplementedError(
            "Published releases are immutable: bulk delete is not permitted. "
            "Deleting a release would orphan the ledger entries that paid for it."
        )


class ImmutableModel(models.Model):
    """Insert-only. See the module docstring."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise NotImplementedError(
                f"{type(self).__name__} is immutable: a published release "
                f"records what was disclosed and cannot be revised. Publish a "
                f"new release for a later period instead."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError(
            f"{type(self).__name__} is immutable: deleting a published release "
            f"would orphan the ledger entries that paid for it."
        )


class BenchmarkRelease(ImmutableModel):
    """One published, differentially private benchmark for one cell."""

    period = models.ForeignKey(
        "ingest.ReportingPeriod", on_delete=models.PROTECT, related_name="releases"
    )
    cohort = models.ForeignKey(
        "collaborations.Cohort", on_delete=models.PROTECT, related_name="releases"
    )
    metric = models.ForeignKey(
        "catalog.MetricDefinition", on_delete=models.PROTECT, related_name="releases"
    )
    n_contributors = models.PositiveIntegerField(
        help_text=(
            "True count, published exactly. Membership is public (DESIGN.md "
            "section 2.2), so this leaks nothing and costs no epsilon. Spending "
            "budget to noise a public quantity would buy no privacy and lose "
            "accuracy."
        )
    )
    epsilon_spent = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        help_text="Total charged to the period's budget for this release.",
    )
    released_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-released_at"]
        constraints = [
            # A cell is released once. Re-releasing would spend budget again and
            # produce a second sample of the same private quantity.
            models.UniqueConstraint(
                fields=["cohort", "metric", "period"],
                name="uniq_release_per_cohort_metric_period",
            ),
            models.CheckConstraint(
                condition=models.Q(epsilon_spent__gt=0),
                name="release_epsilon_spent_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cohort.code}·{self.metric.code}·{self.period.label}"

    @property
    def quantiles_are_ordered(self) -> bool | None:
        """Whether q25 <= median <= q75 in the RELEASED values.

        True quantiles are ordered by definition. Released ones need not be:
        each is drawn independently by the exponential mechanism, so at small N
        or tight epsilon the noise can exceed the spacing between them and the
        third quartile can land below the first.

        That is not a bug to correct. It is the most direct evidence a release
        carries about its own usefulness, and it is measurable without touching
        the data. Seen in the seeded demo at N=6: q25=131.8, q75=126.1.

        Deliberately NOT fixed by sorting. Sorting would be privacy-safe --
        differential privacy is closed under post-processing -- but it would
        conceal the one signal telling a member not to trust this release, and
        replace a visibly broken number with an invisibly meaningless one.

        Returns None when the release has no quantiles to compare.
        """
        values = {
            s.statistic: s.value
            for s in self.statistics.all()
            if s.statistic in {"q25", "median", "q75"}
        }
        if len(values) < 2:
            return None
        ordered = [values[k] for k in ("q25", "median", "q75") if k in values]
        return all(a <= b for a, b in zip(ordered, ordered[1:], strict=False))


#: Reading order for a distribution. Alphabetical ordering puts "median"
#: before "q25", which is nonsense to read: a distribution is understood
#: left-to-right, not lexically.
STATISTIC_DISPLAY_ORDER = ["count", "q25", "median", "q75", "mean", "stddev"]


def display_sorted(statistics):
    """Order released statistics for reading, not for the database."""
    return sorted(
        statistics,
        key=lambda s: (
            STATISTIC_DISPLAY_ORDER.index(s.statistic)
            if s.statistic in STATISTIC_DISPLAY_ORDER
            else len(STATISTIC_DISPLAY_ORDER)
        ),
    )


class ReleasedStatistic(ImmutableModel):
    """One noisy statistic within a release."""

    release = models.ForeignKey(
        BenchmarkRelease, on_delete=models.PROTECT, related_name="statistics"
    )
    statistic = models.CharField(max_length=16)
    mechanism = models.CharField(max_length=32)
    value = models.DecimalField(max_digits=18, decimal_places=6, help_text="Noisy.")
    epsilon_spent = models.DecimalField(max_digits=10, decimal_places=6)

    scale = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Mechanism scale from summarize(). The only quantitative statement "
            "about this release available at publication time for the "
            "exponential mechanism, which returns no accuracy interval."
        ),
    )
    accuracy_lower = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    accuracy_upper = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "NULL for quantiles: OpenDP's summarize() returns no accuracy "
            "interval for the exponential mechanism (ADR-0003, spike finding 4). "
            "Derived by simulation in Sprint 3 (S2-5). Storing a fabricated "
            "interval would be worse than storing none -- a displayed interval "
            "is read as a promise."
        ),
    )

    class Meta:
        ordering = ["release", "statistic"]
        constraints = [
            models.UniqueConstraint(
                fields=["release", "statistic"], name="uniq_statistic_per_release"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.statistic}={self.value} ({self.mechanism})"

    @property
    def has_accuracy_interval(self) -> bool:
        return self.accuracy_lower is not None and self.accuracy_upper is not None
