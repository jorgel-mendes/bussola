"""Property-based tests for the accountant.

The correctness property this whole system exists to guarantee is:

    for ANY sequence of release requests, the ledger sum never exceeds the
    budget.

"Any sequence" is the operative phrase. Three hand-written cases test three
sequences; the interesting failures live in the ones nobody thought to write --
a request of exactly the remaining budget, a long tail of tiny requests,
alternating large and small, a refusal followed by a request that should still
succeed. Generating them is the right tool (SPEC section 7.4).

These run on SQLite as well as Postgres: they are about the accountant's
arithmetic and its refusal logic, not about row-level locking. Concurrency is
`test_concurrency.py`, and it is a genuinely different property.
"""

from __future__ import annotations

import contextlib
import itertools
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from budget.accountant import spend
from budget.exceptions import BudgetExhausted
from budget.models import BudgetPeriod, LedgerEntry
from catalog.models import MetricDefinition, Statistic
from collaborations.models import Cohort, Collaboration, OperatorKind
from ingest.models import ReportingPeriod

# Six decimal places, matching LedgerEntry.epsilon_spent. Values below the
# column's resolution would be silently rounded on write, and a test that
# cannot represent what it asserts is not testing it.
# Shared across the whole class run. Hypothesis executes many examples inside
# one test method and does not roll back between them, so anything with a
# unique constraint needs a name that never repeats -- not one that merely
# differs within a single method.
_labels = itertools.count()

epsilons = st.decimals(
    min_value=Decimal("0.000001"), max_value=Decimal("3"), places=6, allow_nan=False
)
budgets = st.decimals(
    min_value=Decimal("0.0001"), max_value=Decimal("10"), places=4, allow_nan=False
)


class LedgerNeverOverspends(TestCase):
    def setUp(self) -> None:
        # get_or_create, not create: setUp runs per test method but the rows
        # from the previous method may still be present, and a UNIQUE violation
        # here poisons the transaction so that every later query in the class
        # fails with TransactionManagementError instead of the real cause.
        self.collaboration, _ = Collaboration.objects.get_or_create(
            slug="prop",
            defaults={
                "name": "Property Test Collaboration",
                "operator_name": "Test Operator",
                "operator_kind": OperatorKind.ASSOCIATION,
                "min_contributors": 5,
            },
        )
        self.cohort, _ = Cohort.objects.get_or_create(
            collaboration=self.collaboration,
            code="2320",
            defaults={"name": "Cement and lime"},
        )
        self.metric, _ = MetricDefinition.objects.get_or_create(
            collaboration=self.collaboration,
            code="specific_thermal_energy",
            defaults={
                "name": "Specific thermal energy",
                "unit": "MJ/t clinker",
                "lower_bound": Decimal("1760"),
                "upper_bound": Decimal("7100"),
                "bounds_rationale": "Thermodynamic floor to wet-kiln ceiling.",
                "contributions_per_period": 1,
                "statistics": [Statistic.Q25, Statistic.MEDIAN, Statistic.Q75],
            },
        )

    def fresh_budget(self, total: Decimal) -> BudgetPeriod:
        """A budget on its own period, one per Hypothesis example.

        Hypothesis runs many examples inside a single test method and does not
        roll back between them, while BudgetPeriod is one-to-one with a period.
        Reusing one period makes example 2 hit the unique constraint, break the
        transaction, and take every later query down with it.

        Cleaning up between examples is not an option either: LedgerEntry
        deliberately refuses bulk delete. The append-only guard applies to the
        tests that exercise it, which is as it should be.
        """
        period = ReportingPeriod.objects.create(
            collaboration=self.collaboration,
            label=f"2026-{next(_labels):05d}",
            starts=date(2026, 7, 1),
            ends=date(2026, 8, 1),
        )
        return BudgetPeriod.objects.create(period=period, epsilon_total=total)

    def _charge(self, budget, epsilon):
        return spend(
            budget_period=budget,
            cohort=self.cohort,
            metric=self.metric,
            statistic="median",
            mechanism="exponential",
            epsilon=epsilon,
        )

    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, requests=st.lists(epsilons, min_size=1, max_size=25))
    def test_the_ledger_sum_never_exceeds_the_budget(self, total, requests):
        """The property the product exists to guarantee, over any sequence."""
        budget = self.fresh_budget(total)

        for epsilon in requests:
            with contextlib.suppress(BudgetExhausted):
                self._charge(budget, epsilon)

        spent = LedgerEntry.objects.filter(budget_period=budget).aggregate(
            t=Sum("epsilon_spent")
        )["t"] or Decimal("0")

        assert spent <= total, f"over-released: {spent} > {total} for {requests}"

    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, requests=st.lists(epsilons, min_size=1, max_size=25))
    def test_the_ledger_records_exactly_what_was_accepted(self, total, requests):
        """No phantom entries, and no accepted release missing from the ledger.

        A refusal that still wrote an entry would draw the budget down for a
        statistic nobody received. An acceptance that wrote none would be
        unaccounted privacy loss -- the serious direction.
        """
        budget = self.fresh_budget(total)

        accepted = []
        for epsilon in requests:
            try:
                self._charge(budget, epsilon)
                accepted.append(epsilon)
            except BudgetExhausted:
                pass

        entries = LedgerEntry.objects.filter(budget_period=budget)
        assert entries.count() == len(accepted)
        assert sorted(e.epsilon_spent for e in entries) == sorted(accepted)

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, requests=st.lists(epsilons, min_size=1, max_size=25))
    def test_a_refusal_never_changes_the_recorded_total(self, total, requests):
        """Refusal is inert.

        A refused release that moved the total -- in either direction -- would
        mean the ledger reported disclosure that never happened, or concealed
        disclosure that did.
        """
        budget = self.fresh_budget(total)

        def recorded():
            return LedgerEntry.objects.filter(budget_period=budget).aggregate(
                t=Sum("epsilon_spent")
            )["t"] or Decimal("0")

        for epsilon in requests:
            before = recorded()
            try:
                self._charge(budget, epsilon)
            except BudgetExhausted:
                assert recorded() == before, "a refusal moved the ledger total"

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, requests=st.lists(epsilons, min_size=1, max_size=25))
    def test_remaining_budget_is_never_negative(self, total, requests):
        """`remaining()` is shown to operators and drives the release decision.

        A negative remaining would mean the system had already over-released and
        was still reporting a number rather than refusing.
        """
        budget = self.fresh_budget(total)

        for epsilon in requests:
            with contextlib.suppress(BudgetExhausted):
                self._charge(budget, epsilon)
            assert budget.remaining() >= 0, f"negative remaining after {epsilon}"

    # --- boundary-targeted properties -------------------------------------
    #
    # Added after a planted off-by-one (accepting `remaining * 1.0001`) survived
    # every property above. Random generation explores the space broadly but
    # essentially never lands exactly on `remaining` or one unit past it, so the
    # boundary has to be aimed at rather than hoped for. This is the difference
    # between a property test that covers the space and one that covers the
    # cases where budget checks actually go wrong.

    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, prefix=st.lists(epsilons, min_size=0, max_size=10))
    def test_a_request_for_exactly_the_remaining_budget_is_accepted(self, total, prefix):
        """Spending the budget to the last unit is legitimate and must work.

        The opposite error to over-release: a check that refuses here would
        quietly waste budget the collaboration paid for in disclosure risk.
        """
        budget = self.fresh_budget(total)
        for epsilon in prefix:
            with contextlib.suppress(BudgetExhausted):
                self._charge(budget, epsilon)

        remaining = budget.remaining()
        if remaining < Decimal("0.000001"):
            return  # nothing left to spend; not the case under test

        self._charge(budget, remaining)

        assert budget.remaining() == Decimal("0")

    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(total=budgets, prefix=st.lists(epsilons, min_size=0, max_size=10))
    def test_one_unit_past_the_remaining_budget_is_refused(self, total, prefix):
        """The smallest possible over-release must still be refused.

        One unit at the column's resolution -- the tightest the boundary can be
        probed. An off-by-one here is a real over-release, and it is exactly the
        kind of error that survives broad random generation.
        """
        budget = self.fresh_budget(total)
        for epsilon in prefix:
            with contextlib.suppress(BudgetExhausted):
                self._charge(budget, epsilon)

        just_over = budget.remaining() + Decimal("0.000001")

        try:
            self._charge(budget, just_over)
        except BudgetExhausted:
            return

        raise AssertionError(
            f"accepted {just_over} against a remaining budget of "
            f"{budget.remaining()}: over-release by one unit"
        )
