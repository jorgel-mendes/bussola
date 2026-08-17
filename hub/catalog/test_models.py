"""Metric catalog tests.

The catalog is the keystone: it drives agent validation and, from Sprint 2, DP
mechanism selection. A bad metric definition is not a cosmetic problem — it
produces a privacy guarantee that does not hold.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import MetricDefinition

pytestmark = pytest.mark.django_db


def build(collaboration=None, **overrides) -> MetricDefinition:
    defaults = {
        "collaboration": collaboration,
        "code": "test_metric",
        "name": "Test metric",
        "unit": "kWh/t",
        "lower_bound": Decimal("100"),
        "upper_bound": Decimal("500"),
        "bounds_rationale": "Derived from published process limits.",
        "contributions_per_period": 30,
        "statistics": ["count", "median"],
    }
    defaults.update(overrides)
    return MetricDefinition(**defaults)


def test_upper_bound_must_exceed_lower_bound_at_db_level(collaboration):
    """Enforced by CheckConstraint, not only by clean() — an application-level
    check is not a guarantee when data can arrive via a fixture or shell."""
    with pytest.raises(IntegrityError), transaction.atomic():
        MetricDefinition.objects.create(
            collaboration=collaboration,
            code="inverted",
            name="Inverted",
            unit="x",
            lower_bound=Decimal("500"),
            upper_bound=Decimal("100"),
            bounds_rationale="whatever",
        )


def test_clean_rejects_inverted_bounds(collaboration):
    with pytest.raises(ValidationError) as exc:
        build(collaboration, lower_bound=Decimal("500"), upper_bound=Decimal("100")).clean()
    assert "upper_bound" in exc.value.message_dict


def test_clean_requires_bounds_rationale(collaboration):
    """INVARIANT: bounds must be justifiable from public or domain knowledge.

    An empty rationale usually means the bounds were eyeballed from the data,
    which leaks — so the field is required rather than merely encouraged.
    """
    with pytest.raises(ValidationError) as exc:
        build(collaboration, bounds_rationale="   ").clean()
    assert "bounds_rationale" in exc.value.message_dict


def test_clean_rejects_unknown_statistics(collaboration):
    with pytest.raises(ValidationError) as exc:
        build(collaboration, statistics=["median", "kurtosis"]).clean()
    assert "kurtosis" in str(exc.value.message_dict["statistics"])


def test_clamp_bounds_values(collaboration):
    metric = build(collaboration)
    assert metric.clamp(Decimal("50")) == Decimal("100")
    assert metric.clamp(Decimal("900")) == Decimal("500")
    assert metric.clamp(Decimal("300")) == Decimal("300")


def test_is_within_bounds_is_inclusive(collaboration):
    metric = build(collaboration)
    assert metric.is_within_bounds(Decimal("100"))
    assert metric.is_within_bounds(Decimal("500"))
    assert not metric.is_within_bounds(Decimal("99.999999"))


def test_quantile_candidates_span_the_public_bounds(collaboration):
    """Candidates come from the declared bounds, never from observed data."""
    metric = build(collaboration)
    candidates = metric.quantile_candidates(count=5)
    assert candidates[0] == 100.0
    assert candidates[-1] == 500.0
    assert len(candidates) == 5
    assert candidates == sorted(candidates)


def test_quantile_candidates_rejects_degenerate_grid(collaboration):
    with pytest.raises(ValueError):
        build(collaboration).quantile_candidates(count=1)


def test_code_is_unique(collaboration):
    build(collaboration).save()
    with pytest.raises(IntegrityError), transaction.atomic():
        build(collaboration, name="Duplicate").save()
