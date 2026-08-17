"""Collaborations and cohorts -- the tenancy boundary.

A *collaboration* is a set of contributors who have agreed to pool data under
one privacy budget and one governance agreement. It is the unit the market
already uses for this shape of system (AWS Clean Rooms and Decentriq both call
it a collaboration), and it is the right scope for a privacy budget: two
unrelated groups must never draw down each other's epsilon.

The platform is deliberately domain-neutral. The same machinery serves an
industry association benchmarking energy intensity, a university pooling
multi-site study data, and a statistical agency publishing protected
tabulations. Only the metric catalog differs.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class OperatorKind(models.TextChoices):
    """Who occupies the trusted-curator seat.

    This is not decoration. The hub operator sees raw submissions before noise
    is applied (see docs/adr/0002), so the guarantee offered to contributors is
    only as good as their existing reason to trust this operator. Recording the
    kind makes that dependency explicit rather than implied, and it is surfaced
    to contributors in the UI.
    """

    ASSOCIATION = "association", "Industry association or federation"
    UNIVERSITY = "university", "University or research institute"
    AGENCY = "agency", "Statistical or public agency"
    REGULATOR = "regulator", "Sector regulator"
    OTHER = "other", "Other"


class Collaboration(models.Model):
    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    operator_name = models.CharField(
        max_length=160,
        help_text="The organisation running this hub -- the trusted curator.",
    )
    operator_kind = models.CharField(
        max_length=16, choices=OperatorKind.choices, default=OperatorKind.ASSOCIATION
    )

    min_contributors = models.PositiveIntegerField(
        default=5,
        help_text=(
            "Minimum contributors before a cell may be published. Statistical "
            "disclosure control: a 'benchmark' drawn from two contributors is a "
            "disclosure, not a benchmark. Per-collaboration because a 12-plant "
            "consortium and a 400-hospital study need different thresholds."
        ),
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def effective_min_contributors(self) -> int:
        """Fall back to the deployment-wide floor if unset."""
        return self.min_contributors or settings.MIN_CONTRIBUTORS


class Cohort(models.Model):
    """A comparison group within a collaboration.

    Industrial: a sector. Research: a study arm or site type. Agency: a
    geography or classification stratum. Benchmarks are published per
    (cohort, metric, period).
    """

    collaboration = models.ForeignKey(
        Collaboration, on_delete=models.CASCADE, related_name="cohorts"
    )
    code = models.CharField(max_length=32, help_text="e.g. a CNAE code, or a study arm id")
    name = models.CharField(max_length=160)

    class Meta:
        ordering = ["collaboration", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["collaboration", "code"], name="uniq_cohort_code_per_collaboration"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
