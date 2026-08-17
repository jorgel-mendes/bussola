"""Benchmark computation.

SPRINT 1 ONLY — these are EXACT statistics with no privacy protection at all.
They exist to prove the ingestion pipeline end to end before differential
privacy is introduced in Sprint 2, and every page that renders them carries an
explicit warning.

Sprint 2 replaces `compute_exact_benchmark` with an OpenDP-backed release path
that spends privacy budget and writes a ledger entry in the same transaction.
The signature is intended to survive that change.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import QuerySet

from catalog.models import MetricDefinition
from collaborations.models import Cohort
from ingest.models import ReportingPeriod, Submission


@dataclass(frozen=True)
class BenchmarkResult:
    """A computed benchmark for one (cohort, metric, period) cell."""

    cohort: Cohort
    metric: MetricDefinition
    period: ReportingPeriod
    n_contributors: int
    min_contributors: int
    q25: Decimal | None
    median: Decimal | None
    q75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    suppressed: bool
    is_exact: bool = True  # Sprint 1: no noise applied.

    @property
    def suppression_reason(self) -> str | None:
        if not self.suppressed:
            return None
        return (
            f"Fewer than {self.min_contributors} contributing parties "
            f"({self.n_contributors}). Publishing would expose individual contributors."
        )


def _quantile(sorted_values: list[Decimal], q: float) -> Decimal:
    """Linear-interpolation quantile.

    Sprint 2 replaces this entirely: OpenDP's exponential mechanism selects from
    a candidate grid rather than interpolating between observed values, because
    interpolating between two real data points is itself disclosive.
    """
    if not sorted_values:
        raise ValueError("no values")
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = Decimal(str(position - low))
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * weight


def submissions_for(
    cohort: Cohort, metric: MetricDefinition, period: ReportingPeriod
) -> QuerySet[Submission]:
    """Submissions in one cell.

    Filtering on ``cohort`` implicitly scopes to a collaboration, since a cohort
    belongs to exactly one. The metric and period are asserted to match in
    ``compute_exact_benchmark``.
    """
    return Submission.objects.filter(
        contributor__cohort=cohort,
        contributor__is_active=True,
        metric=metric,
        period=period,
    ).select_related("contributor")


def compute_exact_benchmark(
    cohort: Cohort, metric: MetricDefinition, period: ReportingPeriod
) -> BenchmarkResult:
    """Compute exact quartiles for one cell.

    Applies the collaboration's minimum-contributor threshold even though
    nothing is noised yet, so the suppression path is exercised from Sprint 1
    rather than bolted on later.
    """
    collaboration_ids = {cohort.collaboration_id, metric.collaboration_id, period.collaboration_id}
    if len(collaboration_ids) > 1:
        raise ValueError(
            "Cohort, metric and period must belong to the same collaboration. "
            "Computing across collaborations would mix separate privacy budgets."
        )

    threshold = cohort.collaboration.effective_min_contributors
    values = sorted(submissions_for(cohort, metric, period).values_list("value", flat=True))
    n = len(values)

    if n < threshold:
        return BenchmarkResult(
            cohort=cohort,
            metric=metric,
            period=period,
            n_contributors=n,
            min_contributors=threshold,
            q25=None,
            median=None,
            q75=None,
            minimum=None,
            maximum=None,
            suppressed=True,
        )

    return BenchmarkResult(
        cohort=cohort,
        metric=metric,
        period=period,
        n_contributors=n,
        min_contributors=threshold,
        q25=_quantile(values, 0.25),
        median=_quantile(values, 0.50),
        q75=_quantile(values, 0.75),
        minimum=values[0],
        maximum=values[-1],
        suppressed=False,
    )


def contributor_position(value: Decimal, result: BenchmarkResult) -> str:
    """Which quartile a contributor falls in.

    This is the number the member actually cares about, and in Sprint 2 it
    becomes the evaluation's headline metric: the rate at which noisy releases
    still place a contributor in the correct quartile.
    """
    if result.suppressed or result.q25 is None:
        return "unknown"
    if value <= result.q25:
        return "Q1"
    if value <= result.median:
        return "Q2"
    if value <= result.q75:
        return "Q3"
    return "Q4"
