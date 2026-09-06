"""The differentially private release path.

This module replaces `compute_exact_benchmark` as the way a benchmark reaches a
member. The exact path survives only for tests and for the Sprint 1
before/after comparison in the demo.

THE INVARIANT THIS MODULE EXISTS TO HOLD:

    the release and its ledger entries are written in ONE transaction.

A release recorded without a ledger entry is unaccounted privacy loss. A ledger
entry without a release is a charge for a disclosure nobody received. Both are
prevented here, and by `LedgerEntry.release` being NOT NULL at the database
level, and by the tests in `test_releases.py` asserting the invariant in both
directions.

Order of operations matters and is deliberate:

1. suppression is checked FIRST, before any budget is touched. A cell below the
   threshold must cost nothing -- charging epsilon for a release that is then
   refused would drain the budget through cells that were never published.
2. the budget is charged BEFORE the mechanism runs. Doing the work first and
   discovering afterwards that it could not be paid for would mean generating a
   noisy value that has to be discarded, and OpenDP's own accountant would have
   moved regardless.
3. everything happens inside one atomic block, so any failure anywhere unwinds
   the release, its statistics and its ledger entries together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from django.db import transaction

from benchmarks.models import BenchmarkRelease, ReleasedStatistic
from benchmarks.selectors import submissions_for
from budget.accountant import budget_for, spend
from budget.exceptions import CrossCollaborationSpend
from privacy.contexts import PUBLIC_MAX_ROWS, build_context
from privacy.mechanisms import get_mechanism, is_supported

__all__ = ["PUBLIC_MAX_ROWS", "ReleaseOutcome", "per_statistic_epsilon", "release_benchmark",
           "statistics_to_release"]

#: Epsilon is charged at the ledger column's resolution.
EPSILON_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class ReleaseOutcome:
    """What a release attempt produced."""

    release: BenchmarkRelease | None
    n_contributors: int
    min_contributors: int
    suppressed: bool
    statistics: list[ReleasedStatistic] = field(default_factory=list)
    skipped_statistics: list[str] = field(default_factory=list)

    @property
    def suppression_reason(self) -> str | None:
        if not self.suppressed:
            return None
        return (
            f"Fewer than {self.min_contributors} contributing parties "
            f"({self.n_contributors}). Publishing would expose individual contributors."
        )


def statistics_to_release(metric) -> tuple[list[str], list[str]]:
    """Split the catalog's statistics into releasable and skipped.

    Skipped ones are RETURNED, not silently dropped. A statistic listed in the
    catalog that quietly produces no value would leave an operator believing
    they had published something they had not.
    """
    requested = list(metric.statistics or [])
    releasable = [s for s in requested if is_supported(s)]
    skipped = [s for s in requested if not is_supported(s)]
    return releasable, skipped


def per_statistic_epsilon(total: Decimal, count: int) -> Decimal:
    """Split a release's epsilon evenly, rounding UP at the ledger's resolution.

    Rounding up rather than down is deliberate. The charge must never be less
    than what the mechanism actually spends; rounding down would under-charge
    the budget by a fraction of a unit on every release, and those fractions
    accumulate in the direction that matters.

    Public rather than private because `evaluation/sweep.py` charges the same
    way. A sweep that split epsilon differently from the product would be
    reporting the accuracy of a system nobody runs.
    """
    return (total / count).quantize(EPSILON_QUANTUM, rounding=ROUND_CEILING)


@transaction.atomic
def release_benchmark(*, cohort, metric, period, epsilon: Decimal) -> ReleaseOutcome:
    """Publish a differentially private benchmark for one cell.

    Raises BudgetExhausted if the period's budget cannot cover it, in which
    case nothing is written at all. Raises CrossCollaborationSpend if the cell's
    parts belong to different collaborations.
    """
    # CrossCollaborationSpend, not ValueError: this is the same tenancy fault
    # that budget.accountant.spend() raises, and a caller handling one should
    # handle the other. The docstring above promises this type, and an error
    # contract that disagrees with its own documentation is worse than either
    # choice made consistently.
    #
    # Note that benchmarks.selectors.compute_exact_benchmark still raises
    # ValueError for the same condition. That is left alone deliberately: it
    # never spends budget, it has no business importing from `budget`, and it is
    # the Sprint 1 exact path being retired in day 4.
    collaboration_ids = {cohort.collaboration_id, metric.collaboration_id, period.collaboration_id}
    if len(collaboration_ids) > 1:
        raise CrossCollaborationSpend(
            "Cohort, metric and period must belong to the same collaboration. "
            "Releasing across collaborations would mix separate privacy budgets."
        )

    threshold = cohort.collaboration.effective_min_contributors
    values = list(submissions_for(cohort, metric, period).values_list("value", flat=True))
    n_contributors = len(values)

    # 1. Suppression first: a suppressed cell costs no budget.
    if n_contributors < threshold:
        return ReleaseOutcome(
            release=None,
            n_contributors=n_contributors,
            min_contributors=threshold,
            suppressed=True,
        )

    releasable, skipped = statistics_to_release(metric)
    if not releasable:
        raise ValueError(
            f"Metric {metric.code} lists no statistic this build can release. "
            f"Requested: {metric.statistics}. Skipped: {skipped}."
        )

    budget_period = budget_for(period)
    per_statistic = per_statistic_epsilon(epsilon, len(releasable))
    total_charged = per_statistic * len(releasable)

    # The release row is created before its statistics because LedgerEntry.release
    # is NOT NULL -- there is nothing for a spend to point at until it exists.
    # epsilon_spent is final at creation, not accumulated afterwards, because
    # BenchmarkRelease is immutable and cannot be updated later.
    release = BenchmarkRelease.objects.create(
        period=period,
        cohort=cohort,
        metric=metric,
        n_contributors=n_contributors,
        epsilon_spent=total_charged,
    )

    context = build_context(
        values,
        contributions=metric.contributions_per_period,
        epsilon=total_charged,
        split_evenly_over=len(releasable),
    )

    released: list[ReleasedStatistic] = []
    for statistic in releasable:
        mechanism = get_mechanism(statistic)

        # Charge BEFORE running the mechanism. spend() joins this transaction,
        # so a refusal here unwinds the release and every statistic already
        # published in this call -- a partial release is worse than none.
        spend(
            budget_period=budget_period,
            cohort=cohort,
            metric=metric,
            statistic=statistic,
            mechanism=mechanism.mechanism_name,
            epsilon=per_statistic,
            release=release,
        )

        outcome = mechanism.release(context, metric, per_statistic)
        released.append(
            ReleasedStatistic.objects.create(
                release=release,
                statistic=outcome.statistic,
                mechanism=outcome.mechanism,
                value=outcome.value,
                epsilon_spent=outcome.epsilon,
                scale=outcome.scale,
                accuracy_lower=outcome.accuracy_lower,
                accuracy_upper=outcome.accuracy_upper,
            )
        )

    return ReleaseOutcome(
        release=release,
        n_contributors=n_contributors,
        min_contributors=threshold,
        suppressed=False,
        statistics=released,
        skipped_statistics=skipped,
    )
