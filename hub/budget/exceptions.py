"""Budget errors.

Separate module so that both the models and the accountant can raise these
without importing each other.
"""

from __future__ import annotations

from decimal import Decimal


class BudgetError(Exception):
    """Base class for privacy-budget failures."""


class BudgetExhausted(BudgetError):
    """A release was refused because it would exceed the period's budget.

    Refusing is the correct behaviour and the designed one (REVIEW section F1):
    the system declines rather than leaking. Serving a stale release instead
    would be worse -- it hides from the operator that the budget is gone.

    Carries the numbers so the operator is told *how much* was left, not merely
    that something failed.
    """

    def __init__(self, remaining: Decimal, requested: Decimal) -> None:
        self.remaining = remaining
        self.requested = requested
        super().__init__(
            f"Privacy budget exhausted: requested epsilon={requested}, "
            f"only {remaining} remains for this period. No release was made."
        )


class BudgetNotConfigured(BudgetError):
    """A release was attempted for a period with no budget defined.

    Deliberately an error rather than a default. Defaulting to some epsilon
    would mean a period could spend privacy budget nobody ever authorised.
    """


class UnsupportedAccountant(BudgetError):
    """The budget declares a composition accountant this build cannot honour.

    Raised rather than silently falling back to basic composition. A zCDP
    budget accounted as if it were basic would report the wrong remaining
    epsilon -- a plausible number that is wrong, which is the defect class
    Sprint 1 shipped three of.
    """
