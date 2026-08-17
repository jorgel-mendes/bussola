"""Reporting periods and contributor submissions.

Three rules in this module have privacy consequences rather than merely
data-hygiene ones. All three are enforced at the database level where possible,
because an application-level check is not a guarantee.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


class PeriodStatus(models.TextChoices):
    OPEN = "open", "Open for submissions"
    CLOSED = "closed", "Closed"
    RELEASED = "released", "Released"


class ReportingPeriod(models.Model):
    collaboration = models.ForeignKey(
        "collaborations.Collaboration", on_delete=models.CASCADE, related_name="periods"
    )
    label = models.CharField(max_length=16, help_text="e.g. 2026-07")
    starts = models.DateField()
    ends = models.DateField()
    status = models.CharField(
        max_length=16, choices=PeriodStatus.choices, default=PeriodStatus.OPEN
    )

    class Meta:
        ordering = ["-starts"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends__gt=models.F("starts")),
                name="period_ends_after_starts",
            ),
            models.UniqueConstraint(
                fields=["collaboration", "label"], name="uniq_period_label_per_collaboration"
            ),
        ]

    def __str__(self) -> str:
        return self.label

    @property
    def accepts_submissions(self) -> bool:
        return self.status == PeriodStatus.OPEN


class Submission(models.Model):
    """One contributor's aggregate for one metric in one period.

    RULE 1 -- Idempotency. ``uniq_submission_per_contributor_period_metric``
    means a resubmission updates in place. Without it a contributor could submit
    twice and double its weight in the aggregate, breaking the per-contributor
    sensitivity bound that the entire privacy guarantee rests on.

    RULE 2 -- Immutability after release. Once the period is RELEASED,
    submissions freeze. Editing inputs after a release and re-releasing would
    spend privacy budget the accountant never charged.

    RULE 3 -- Collaboration integrity. The contributor, period and metric must
    all belong to the *same* collaboration. A submission that straddles two
    collaborations would pull one group's data into another group's benchmark
    and draw down the wrong privacy budget. See ``clean()``.
    """

    contributor = models.ForeignKey(
        "contributors.Contributor", on_delete=models.CASCADE, related_name="submissions"
    )
    period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="submissions")
    metric = models.ForeignKey(
        "catalog.MetricDefinition", on_delete=models.PROTECT, related_name="submissions"
    )
    value = models.DecimalField(max_digits=18, decimal_places=6)
    n_records = models.PositiveIntegerField(help_text="Underlying rows this value aggregates.")
    agent_version = models.CharField(max_length=32)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["contributor", "period", "metric"],
                name="uniq_submission_per_contributor_period_metric",
            ),
            models.CheckConstraint(
                condition=models.Q(n_records__gte=1),
                name="submission_n_records_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contributor.name} · {self.metric.code} · {self.period.label}"

    def clean(self) -> None:
        errors: dict[str, str] = {}

        if self.period_id and not self.period.accepts_submissions:
            errors["period"] = f"Period {self.period.label} is {self.period.status}."

        if (
            self.metric_id
            and self.value is not None
            and not self.metric.is_within_bounds(self.value)
        ):
            errors["value"] = (
                f"Value {self.value} is outside the declared bounds "
                f"[{self.metric.lower_bound}, {self.metric.upper_bound}] "
                f"for {self.metric.code}."
            )

        # RULE 3. Cannot be a database constraint without denormalising the
        # collaboration onto Submission, so it is enforced here and in the API,
        # and covered by an explicit test.
        if self.contributor_id and self.period_id and self.metric_id:
            ids = {
                self.contributor.collaboration_id,
                self.period.collaboration_id,
                self.metric.collaboration_id,
            }
            if len(ids) > 1:
                errors["metric"] = (
                    "Contributor, period and metric must belong to the same collaboration. "
                    "A submission spanning collaborations would contaminate another "
                    "group's benchmark and draw down the wrong privacy budget."
                )

        if errors:
            raise ValidationError(errors)
