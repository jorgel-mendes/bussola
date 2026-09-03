"""Mechanism registry.

Selection is data-driven: `MetricDefinition.statistics` is a catalog field, so
which statistics a metric publishes is an admin decision, not a code change
(DESIGN.md section 3.3). Adding a statistic type later means registering a
class here, not editing the release path.

Sprint 2 registers quantiles only. Count, mean and standard deviation are
deliberately absent -- see `quantile.py` for why, and note that the release
path reports what it skipped rather than silently ignoring it. A statistic
listed in the catalog that produces no released value must be visible, or an
operator will believe they published something they did not.
"""

from __future__ import annotations

from privacy.mechanisms.base import Mechanism
from privacy.mechanisms.quantile import QUANTILE_ALPHA, QuantileMechanism

_REGISTRY: dict[str, type[Mechanism]] = dict.fromkeys(QUANTILE_ALPHA, QuantileMechanism)


def is_supported(statistic: str) -> bool:
    return statistic in _REGISTRY


def supported_statistics() -> list[str]:
    return sorted(_REGISTRY)


def get_mechanism(statistic: str) -> Mechanism:
    try:
        mechanism_class = _REGISTRY[statistic]
    except KeyError as exc:
        raise UnsupportedStatistic(
            f"No mechanism is registered for {statistic!r}. "
            f"Registered: {', '.join(supported_statistics())}."
        ) from exc
    return mechanism_class(statistic)


class UnsupportedStatistic(Exception):
    """A statistic was requested that no registered mechanism can release."""
