"""Construction of the OpenDP context every release runs inside.

This lives here, rather than inline in `benchmarks.releases`, for one reason:
the privacy-utility sweep in `evaluation/` has to measure THE MECHANISM THE
PRODUCT SHIPS. A sweep that builds its own context is measuring a copy, and a
copy drifts -- silently, and in the direction that flatters the results, because
nobody re-checks a harness that is producing plausible numbers.

So the release path and the sweep call the same function. If the privacy unit,
the loss, the split or the margin changes, both move together or neither does.
"""

from __future__ import annotations

from decimal import Decimal

import opendp.prelude as dp
import polars as pl

dp.enable_features("contrib")

#: Public upper bound on rows in one cell, declared to OpenDP as a Margin.
#: Membership is public (DESIGN.md section 2.2), so a public bound on the row
#: count leaks nothing -- and OpenDP requires one for quantile queries
#: (ADR-0003, blocker 3). Deliberately generous and constant: deriving it from
#: the actual number of contributors would make it a function of the data.
PUBLIC_MAX_ROWS = 10_000


def build_context(
    values,
    *,
    contributions: int,
    epsilon: Decimal | float,
    split_evenly_over: int,
):
    """Build the compositor a cell's statistics are released from.

    `split_evenly_over` is the number of statistics that will be drawn from
    this context. OpenDP divides the loss across them, which is the same split
    `benchmarks.releases.per_statistic_epsilon` charges to the ledger -- the two
    must agree, or the ledger records a different price from the one paid.
    """
    return dp.Context.compositor(
        data=pl.LazyFrame({"value": [float(v) for v in values]}),
        privacy_unit=dp.unit_of(contributions=contributions),
        privacy_loss=dp.loss_of(epsilon=float(epsilon)),
        split_evenly_over=split_evenly_over,
        margins=[dp.polars.Margin(max_length=PUBLIC_MAX_ROWS)],
    )
