"""The flagship test: concurrent releases must not double-spend the budget.

Why this is the most defensible test in the project (SPEC section 7.3):

Two releases are requested at the same instant against a budget with room for
one. Both read "epsilon remaining = 0.1", both conclude they can afford it,
both write a ledger entry. The period has now spent twice its budget. Nothing
raises. The dashboard renders. The ledger balances against itself. And the
privacy guarantee the whole product exists to provide is void.

There is no way to catch that by reading the code, and no way to catch it with
a sequential test. It needs real threads racing on a real transactional
database.

REQUIRES POSTGRES. `select_for_update()` is a silent no-op on SQLite, so on
SQLite these tests would pass while proving nothing whatsoever -- the exact
"looks fine, is not verified" failure mode that put three defects into Sprint 1.
They skip rather than lie, and `hub/test_postgres_guard.py` fails the build if
they skip in an environment that was supposed to run them.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.db import connection, connections
from django.db.models import Sum

from budget.accountant import spend
from budget.exceptions import BudgetExhausted
from budget.models import BudgetPeriod, LedgerEntry
from config.settings.test import using_postgres

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not using_postgres(),
        reason=(
            "select_for_update() is a no-op on SQLite; this test would pass "
            "vacuously. Run against Postgres: "
            "DATABASE_URL=postgres://bussola:bussola@localhost:5432/bussola_test"
        ),
    ),
]


def _make_release(budget, cohort, metric):
    """One release, shared by every racing thread.

    Created before the race so that all threads contend on the budget row and
    nothing else -- creating it inside the workers would race on the unique
    constraint instead and test the wrong thing.
    """
    from benchmarks.models import BenchmarkRelease

    return BenchmarkRelease.objects.create(
        period=budget.period,
        cohort=cohort,
        metric=metric,
        n_contributors=8,
        epsilon_spent=Decimal("1.000000"),
    )


def _race(budget, cohort, metric, *, threads: int, epsilon: Decimal):
    """Fire `threads` simultaneous spends of `epsilon`, return (ok, refused).

    A Barrier is used rather than merely starting the threads: without it the
    first thread routinely finishes before the last one starts, the lock is
    never contended, and the test silently stops testing anything.
    """
    release = _make_release(budget, cohort, metric)
    gate = threading.Barrier(threads)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            gate.wait(timeout=30)
            try:
                spend(
                    budget_period=budget,
                    cohort=cohort,
                    metric=metric,
                    statistic=f"q{index}",
                    mechanism="exponential",
                    epsilon=epsilon,
                    release=release,
                )
                result = "ok"
            except BudgetExhausted:
                result = "refused"
            with lock:
                outcomes.append(result)
        finally:
            # Each thread opens its own connection; leaking them wedges the
            # test database teardown.
            connections.close_all()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))

    return outcomes.count("ok"), outcomes.count("refused")


@pytest.fixture
def budget(period) -> BudgetPeriod:
    return BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("0.7000"))


def test_k_parallel_releases_against_a_budget_affording_k_minus_one(
    budget, cohort, metric
):
    """Eight simultaneous releases, budget for seven. Exactly one is refused.

    If this fails with eight successes, the accountant does not hold under
    load and every privacy claim the product makes is unsupported.
    """
    ok, refused = _race(budget, cohort, metric, threads=8, epsilon=Decimal("0.100000"))

    assert ok == 7, f"expected 7 successful releases, got {ok}"
    assert refused == 1, f"expected exactly 1 refusal, got {refused}"
    assert LedgerEntry.objects.count() == 7


def test_the_ledger_sum_never_exceeds_the_budget_under_contention(
    budget, cohort, metric
):
    """The invariant itself, stated directly.

    Heavier contention than the case above: twelve threads against a budget
    affording seven. The counts matter less here than the sum -- whatever the
    interleaving, total epsilon spent must never exceed what was authorised.
    """
    ok, refused = _race(budget, cohort, metric, threads=12, epsilon=Decimal("0.100000"))

    total = LedgerEntry.objects.aggregate(t=Sum("epsilon_spent"))["t"] or Decimal("0")

    assert total <= budget.epsilon_total, (
        f"OVER-RELEASED: ledger sums to {total} against a budget of "
        f"{budget.epsilon_total}. The privacy guarantee is void."
    )
    assert ok == 7
    assert refused == 5


def test_a_single_oversized_release_cannot_slip_through_under_contention(
    budget, cohort, metric
):
    """Uneven epsilon, so the race is not a tidy division of the budget.

    Three threads want 0.3 and three want 0.1 against a budget of 0.7. Any
    combination is legal as long as the total fits; the assertion is on the
    sum, not on which requests won.
    """
    release = _make_release(budget, cohort, metric)
    gate = threading.Barrier(6)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(epsilon: Decimal) -> None:
        try:
            gate.wait(timeout=30)
            try:
                spend(
                    budget_period=budget,
                    cohort=cohort,
                    metric=metric,
                    statistic="median",
                    mechanism="exponential",
                    epsilon=epsilon,
                    release=release,
                )
                r = "ok"
            except BudgetExhausted:
                r = "refused"
            with lock:
                outcomes.append(r)
        finally:
            connections.close_all()

    sizes = [Decimal("0.300000")] * 3 + [Decimal("0.100000")] * 3
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(worker, sizes))

    total = LedgerEntry.objects.aggregate(t=Sum("epsilon_spent"))["t"] or Decimal("0")

    assert total <= budget.epsilon_total, (
        f"OVER-RELEASED: {total} spent against a budget of {budget.epsilon_total}."
    )
    assert "ok" in outcomes, "contention must not deadlock every request"


def test_select_for_update_is_actually_available_here():
    """Guard against the test file passing for the wrong reason.

    If this ever runs somewhere `select_for_update()` is a no-op, every test
    above becomes theatre. Asserting the capability directly means the file
    cannot quietly degrade into passing without testing anything.
    """
    assert connection.features.has_select_for_update, (
        "This backend does not support SELECT ... FOR UPDATE, so the "
        "concurrency tests above prove nothing."
    )
