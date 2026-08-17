"""BudgetPeriod and the append-only LedgerEntry.

Sprint 2. See SPEC section 5.4 -- the accountant's critical section uses
select_for_update() and therefore requires Postgres, not SQLite.
"""
