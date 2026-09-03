"""Quantiles via the exponential mechanism.

This is the design insight of the whole project (SPEC section 6.1). The
exponential mechanism for quantiles operates on RANKS, not values, so its
sensitivity is 1 regardless of whether the metric is measured in thousands of
MJ/t or in parts per million. A DP mean pays (upper - lower) x contributions in
sensitivity, so a metric with wide physical bounds is destroyed by noise.

Industrial benchmarking wants quartiles. Quartiles are the cheapest thing
differential privacy can give you. The product requirement and the privacy
mathematics point the same way, which is rare and worth saying out loud.

Consequence, and the reason this is the only mechanism registered in Sprint 2:
means and standard deviations are far worse value per unit of epsilon. Measured
on the seeded catalog at epsilon=1 split three ways, a DP mean's accuracy
interval came back wider than the sum being estimated. Shipping only the
statistic that works is a position, not a gap.
"""

from __future__ import annotations

from decimal import Decimal

import opendp.prelude as dp
import polars as pl

from privacy.mechanisms.base import Mechanism, MechanismOutcome

dp.enable_features("contrib")

#: alpha for each quantile statistic in the catalog.
QUANTILE_ALPHA = {"q25": 0.25, "median": 0.5, "q75": 0.75}


class QuantileMechanism(Mechanism):
    mechanism_name = "exponential"

    def __init__(self, statistic: str) -> None:
        if statistic not in QUANTILE_ALPHA:
            raise ValueError(f"{statistic!r} is not a quantile statistic.")
        super().__init__(statistic)
        self.alpha = QUANTILE_ALPHA[statistic]

    def build_query(self, context, metric):
        # Candidates come from the metric's PUBLIC bounds. Deriving the grid
        # from the submitted data would leak: the grid is part of the output
        # specification, not of the private input. The spike also measured that
        # narrowing the grid toward the data buys no accuracy anyway
        # (ADR-0003), which removes the temptation.
        candidates = metric.quantile_candidates()
        return context.query().select(
            pl.col("value").dp.quantile(self.alpha, candidates)
        )

    def release(self, context, metric, epsilon: Decimal) -> MechanismOutcome:
        query = self.build_query(context, metric)

        # summarize() BEFORE release(): it costs no budget, and release()
        # consumes the query. For the exponential mechanism it returns the
        # scale and a null accuracy (ADR-0003, spike finding 4).
        summary = query.summarize(alpha=0.05)
        scale = _column_value(summary, "scale")
        accuracy = _column_value(summary, "accuracy")

        value = query.release().collect().item()

        return MechanismOutcome(
            statistic=self.statistic,
            mechanism=self.mechanism_name,
            value=Decimal(str(value)),
            epsilon=epsilon,
            scale=None if scale is None else Decimal(str(scale)),
            # Null for quantiles today. Sprint 3 (S2-5) derives the interval by
            # simulation; storing a fabricated one now would be worse than
            # storing none, because a displayed interval is read as a promise.
            accuracy_lower=None if accuracy is None else Decimal(str(value - accuracy)),
            accuracy_upper=None if accuracy is None else Decimal(str(value + accuracy)),
        )


def _column_value(summary, column: str):
    """Read one cell from an OpenDP summary frame, tolerating absence."""
    if column not in summary.columns:
        return None
    values = summary[column].to_list()
    return values[0] if values else None
