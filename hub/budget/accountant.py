"""The privacy-budget accountant.

This module owns the one critical section in the system. Everything else can
be wrong and produce a bad number; this being wrong produces a *good-looking*
number backed by no privacy guarantee at all.

The concurrency problem, concretely: two releases are requested at the same
moment against a budget with room for one. Both read "epsilon remaining = 1.0",
both decide they can afford 1.0, both write an entry, and the period has now
spent 2.0 of a 1.0 budget. Nothing errors. The dashboard looks fine. The
guarantee is void.

``select_for_update()`` on the BudgetPeriod row is what prevents it: the second
transaction blocks until the first commits, then re-reads the ledger and sees
the real total. Note that this is a *no-op on SQLite* -- which is why CI runs
Postgres and why the concurrency test refuses to pass vacuously.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from budget.exceptions import (
    BudgetExhausted,
    BudgetNotConfigured,
    CrossCollaborationSpend,
)
from budget.models import BudgetPeriod, LedgerEntry


def budget_for(period) -> BudgetPeriod:
    """The budget for a period, or an error.

    Deliberately not ``get_or_create`` with a default. A period that silently
    acquired a default budget could spend privacy nobody authorised.
    """
    try:
        return period.budget
    except BudgetPeriod.DoesNotExist as exc:
        raise BudgetNotConfigured(
            f"Period {period.label} has no privacy budget. An analyst must set "
            f"one before any statistic can be released."
        ) from exc


@transaction.atomic
def spend(
    *,
    budget_period: BudgetPeriod,
    cohort,
    metric,
    statistic: str,
    mechanism: str,
    epsilon: Decimal,
) -> LedgerEntry:
    """Charge ``epsilon`` against a period's budget, or refuse.

    Returns the LedgerEntry on success; raises BudgetExhausted on refusal.

    MUST be called inside the same transaction as the release it pays for. The
    ``@transaction.atomic`` here makes the check-and-write atomic on its own,
    but it joins an outer atomic block when one is open -- which is exactly how
    the release path uses it, so that a committed release and its ledger entry
    are the same commit.

    Keyword-only on purpose: a positional call site that swapped ``cohort`` and
    ``metric``, or ``statistic`` and ``mechanism``, would still run and would
    still write a plausible-looking entry against the wrong cell.
    """
    if epsilon <= 0:
        raise ValueError(
            f"Refusing to record a non-positive spend (epsilon={epsilon}). "
            f"A zero-cost release is not a release."
        )

    # THE CRITICAL SECTION. Lock the budget row first, then read the ledger.
    # Locking before summing is what serialises concurrent releases; summing
    # first and locking after would leave the same race wide open.
    locked = BudgetPeriod.objects.select_for_update().get(pk=budget_period.pk)
    locked.check_accountant_supported()

    # The tenancy boundary, in its budget form (ADR-0004). budget_period, cohort
    # and metric arrive as independent arguments, and nothing about their types
    # stops them belonging to three different collaborations. Charging one
    # group's budget for another's cohort would draw down the wrong epsilon and
    # file the ledger row under a tenant that never authorised it.
    #
    # Enforced here rather than trusted to callers, for the same reason
    # compute_exact_benchmark refuses across collaborations and Submission.clean
    # enforces RULE 3: this is the last point before the spend is durable.
    collaboration_ids = {
        locked.period.collaboration_id,
        cohort.collaboration_id,
        metric.collaboration_id,
    }
    if len(collaboration_ids) > 1:
        raise CrossCollaborationSpend(
            "Budget period, cohort and metric must belong to the same "
            "collaboration. Spending across collaborations would draw down the "
            "wrong group's privacy budget and corrupt both audit trails. "
            f"Got collaboration ids {sorted(collaboration_ids)}."
        )

    already = LedgerEntry.objects.filter(budget_period=locked).aggregate(
        total=Sum("epsilon_spent")
    )["total"] or Decimal("0")

    remaining = locked.epsilon_total - already
    if epsilon > remaining:
        raise BudgetExhausted(remaining=remaining, requested=epsilon)

    return LedgerEntry.objects.create(
        budget_period=locked,
        cohort=cohort,
        metric=metric,
        statistic=statistic,
        mechanism=mechanism,
        epsilon_spent=epsilon,
    )
