"""The metric catalog -- the keystone table.

The catalog drives *both* agent-side validation and hub-side DP mechanism
selection. Get this right and most of the rest of the system is configuration
rather than code.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

QUANTILE_CANDIDATE_COUNT = 200


class ValueType(models.TextChoices):
    CONTINUOUS = "continuous", "Continuous"
    COUNT = "count", "Count"


class Statistic(models.TextChoices):
    """Statistics a metric can publish.

    Cost ordering matters (SPEC section 6.1): quantiles are released with the
    exponential mechanism, whose sensitivity is rank-based and therefore
    *independent of the value scale*. Means pay (upper - lower) x contributions.
    So quartiles -- exactly what industrial benchmarking wants -- are the
    cheapest thing DP can give us. Lead with them.
    """

    COUNT = "count", "Record count"
    Q25 = "q25", "First quartile"
    MEDIAN = "median", "Median"
    Q75 = "q75", "Third quartile"
    MEAN = "mean", "Mean"
    STDDEV = "stddev", "Standard deviation"


class MetricDefinition(models.Model):
    collaboration = models.ForeignKey(
        "collaborations.Collaboration", on_delete=models.CASCADE, related_name="metrics"
    )
    code = models.SlugField(max_length=50, help_text="e.g. energy_per_tonne")
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=32, help_text="e.g. kWh/t")
    value_type = models.CharField(
        max_length=16, choices=ValueType.choices, default=ValueType.CONTINUOUS
    )
    is_active = models.BooleanField(default=True)

    # --- DP-critical fields ------------------------------------------------
    lower_bound = models.DecimalField(max_digits=18, decimal_places=6)
    upper_bound = models.DecimalField(max_digits=18, decimal_places=6)
    bounds_rationale = models.TextField(
        help_text=(
            "REQUIRED. Why these bounds, from public or domain knowledge -- never "
            "derived from the submitted data, which would leak. Displayed to members "
            "next to every published benchmark."
        )
    )
    contributions_per_period = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            "The privacy unit: how many ROWS one contributor adds to the table the "
            "hub runs DP over. Maps to OpenDP's dp.unit_of(contributions=N). "
            "Keep this at 1 while the agent submits one aggregate per period — "
            "removing a contributor removes exactly one row. This is NOT the number "
            "of underlying observations behind that aggregate; that is recorded "
            "separately as Submission.n_records and carries no privacy meaning."
        ),
    )
    statistics = models.JSONField(
        default=list,
        help_text="Statistics to publish, e.g. ['count', 'q25', 'median', 'q75'].",
    )

    class Meta:
        ordering = ["collaboration", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(upper_bound__gt=models.F("lower_bound")),
                name="metric_upper_bound_gt_lower_bound",
            ),
            # Codes are unique per collaboration, not globally: two unrelated
            # collaborations may both define "energy_per_tonne" with different
            # bounds and different rationales.
            models.UniqueConstraint(
                fields=["collaboration", "code"], name="uniq_metric_code_per_collaboration"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"

    # --- validation --------------------------------------------------------

    def clean(self) -> None:
        errors: dict[str, str] = {}

        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.upper_bound <= self.lower_bound
        ):
            errors["upper_bound"] = "Upper bound must be greater than lower bound."

        if not (self.bounds_rationale or "").strip():
            errors["bounds_rationale"] = (
                "A rationale is required. Bounds must be justifiable from public or "
                "domain knowledge; deriving them from the data leaks information."
            )

        valid = set(Statistic.values)
        unknown = [s for s in (self.statistics or []) if s not in valid]
        if unknown:
            errors["statistics"] = f"Unknown statistic(s): {', '.join(sorted(unknown))}."

        if errors:
            raise ValidationError(errors)

    # --- derived -----------------------------------------------------------

    def quantile_candidates(self, count: int = QUANTILE_CANDIDATE_COUNT) -> list[float]:
        """Candidate grid for the exponential mechanism (Sprint 2).

        Derived from the *public* bounds, never from the data. The exponential
        mechanism selects from candidates rather than perturbing a value, so
        this grid -- not a sensitivity term -- sets the output resolution.
        """
        if count < 2:
            raise ValueError("Need at least 2 candidates.")
        lo, hi = float(self.lower_bound), float(self.upper_bound)
        step = (hi - lo) / (count - 1)
        return [lo + step * i for i in range(count)]

    def clamp(self, value: Decimal) -> Decimal:
        """Clamp to the declared bounds. Bounding contributions is what makes
        sensitivity finite; an unclamped value would make the guarantee vacuous."""
        return min(max(value, self.lower_bound), self.upper_bound)

    def is_within_bounds(self, value: Decimal) -> bool:
        return self.lower_bound <= value <= self.upper_bound
