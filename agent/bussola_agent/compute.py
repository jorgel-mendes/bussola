"""Local aggregate computation.

This is the whole point of the agent: raw per-record data never leaves the
plant. Only the aggregate defined here is transmitted. Everything in this module
runs on the plant's own machine, against the plant's own file.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import polars as pl

from bussola_contracts import MetricSpec


class ComputationError(RuntimeError):
    """Raised when local data cannot be reduced to a submittable aggregate."""


def load_records(
    path: Path,
    column: str,
    *,
    period: str | None = None,
    period_column: str = "period",
) -> pl.Series:
    """Read the plant's local file and return the metric column for one period.

    CSV for Sprint 1. A production agent would read the plant historian
    (PI, Aspen IP.21) here; the boundary is the same either way.

    If ``period`` is given and the file carries a period column, records are
    filtered to that period. Submitting a value computed over the wrong window
    would be silently wrong -- the number looks plausible and nothing errors --
    so this filter is applied strictly and an empty result is a hard failure.
    """
    if not path.exists():
        raise ComputationError(f"Data file not found: {path}")

    try:
        frame = pl.read_csv(path)
    except Exception as exc:
        raise ComputationError(f"Could not read {path}: {exc}") from exc

    if column not in frame.columns:
        raise ComputationError(
            f"Column '{column}' not found in {path}. Available: {', '.join(frame.columns)}"
        )

    if period is not None and period_column in frame.columns:
        frame = frame.filter(pl.col(period_column).cast(pl.String) == period)
        if frame.height == 0:
            raise ComputationError(
                f"No records for period '{period}' in {path}. "
                "Check the period label matches the data."
            )

    series = frame[column].drop_nulls()
    if series.len() == 0:
        raise ComputationError(f"Column '{column}' in {path} has no non-null values.")

    return series


def local_mean(series: pl.Series) -> Decimal:
    """Reduce the plant's records to a single period aggregate.

    Sprint 1 submits the mean. The statistic submitted here is the plant's
    *local* summary; the DP treatment happens at the hub, across plants
    (SPEC section 3.3 — central model, not local).
    """
    try:
        return Decimal(str(series.mean()))
    except (InvalidOperation, TypeError) as exc:
        raise ComputationError(f"Could not compute a mean from column values: {exc}") from exc


def check_bounds(value: Decimal, spec: MetricSpec) -> None:
    """Fail locally rather than as an opaque 422 from the hub.

    A value outside the physically justified bounds nearly always means a unit
    error or a faulty sensor, and the operator standing at the terminal is far
    better placed to diagnose it than the hub is.
    """
    if not (spec.lower_bound <= value <= spec.upper_bound):
        raise ComputationError(
            f"Computed value {value} is outside the declared bounds "
            f"[{spec.lower_bound}, {spec.upper_bound}] {spec.unit} for '{spec.code}'.\n"
            f"Bounds rationale: {spec.bounds_rationale}\n"
            "This usually indicates a unit conversion error or a faulty sensor. "
            "Nothing has been submitted."
        )
