"""Mechanism strategy interface.

One class per statistic type, selected from the catalog at release time, so
adding a statistic is a registration rather than a branch in an if/elif chain
(DESIGN.md section 3.3).

The interface is deliberately narrow: a mechanism knows how to build its own
OpenDP query and how to name itself for the ledger. It does NOT know about
budgets, transactions or the database. Budget accounting lives in
`budget.accountant`, and the two are joined only in `benchmarks.releases`,
where the release and its ledger entry are written in one transaction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MechanismOutcome:
    """One released statistic, and what it cost.

    `accuracy_lower`/`accuracy_upper` are None for the exponential mechanism.
    That is not an oversight: OpenDP's summarize() returns no accuracy interval
    for quantiles, only the mechanism scale (ADR-0003, spike finding 4). The
    interval must come from simulation, which is Sprint 3 work (S2-5).

    `scale` is recorded anyway. It is the one quantitative statement about the
    mechanism available at release time, it costs nothing, and discarding it
    would throw away the input the Sprint 3 interval will be built from.
    """

    statistic: str
    mechanism: str
    value: Decimal
    epsilon: Decimal
    scale: Decimal | None = None
    accuracy_lower: Decimal | None = None
    accuracy_upper: Decimal | None = None


class Mechanism(ABC):
    """A differentially private release strategy for one statistic."""

    #: Ledger label for the mechanism family, e.g. "exponential".
    mechanism_name: str

    def __init__(self, statistic: str) -> None:
        self.statistic = statistic

    @abstractmethod
    def build_query(self, context, metric):
        """Return an unreleased OpenDP query against `context`."""

    @abstractmethod
    def release(self, context, metric, epsilon: Decimal) -> MechanismOutcome:
        """Run the mechanism and return the noisy value.

        Implementations MUST call summarize() before release(). summarize()
        costs no privacy budget and is the only source of the mechanism's
        scale; calling it afterwards would be too late, because release()
        consumes the query.
        """
