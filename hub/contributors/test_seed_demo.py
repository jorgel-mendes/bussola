"""Smoke tests for the seed_demo command.

This command is on the demo path: it runs before the recorded demonstration and
inside docker-compose. A failure here would surface at the worst possible
moment, so it is tested rather than trusted.
"""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command

from catalog.models import MetricDefinition
from collaborations.models import Cohort
from contributors.models import ApiToken, Contributor, hash_token
from ingest.models import ReportingPeriod

pytestmark = pytest.mark.django_db


def test_seeds_a_working_consortium():
    call_command("seed_demo", contributors=6, periods=3, verbosity=0)

    assert Cohort.objects.count() == 2
    assert Contributor.objects.count() == 6
    assert MetricDefinition.objects.count() == 2
    assert ReportingPeriod.objects.count() == 3
    assert ApiToken.objects.active().count() == 6


def test_is_idempotent():
    """Safe to re-run against an existing database."""
    call_command("seed_demo", contributors=6, periods=3, verbosity=0)
    call_command("seed_demo", contributors=6, periods=3, verbosity=0)

    assert Contributor.objects.count() == 6
    assert MetricDefinition.objects.count() == 2
    assert ReportingPeriod.objects.count() == 3
    # Re-seeding rotates tokens rather than accumulating them.
    assert ApiToken.objects.active().count() == 6


def test_seeded_metrics_carry_a_substantive_bounds_rationale():
    """The rationale is displayed to members and must survive model validation.

    A seed that produced an empty or throwaway rationale would model exactly the
    habit this field exists to prevent.
    """
    call_command("seed_demo", contributors=6, periods=3, verbosity=0)

    for metric in MetricDefinition.objects.all():
        metric.full_clean()
        assert len(metric.bounds_rationale) > 100
        assert metric.upper_bound > metric.lower_bound


def test_tokens_out_writes_usable_raw_tokens(tmp_path):
    """docker-compose reads this file; the raw keys must actually authenticate."""
    out = tmp_path / "tokens.json"
    call_command("seed_demo", contributors=3, periods=2, tokens_out=out, verbosity=0)

    tokens = json.loads(out.read_text())
    assert set(tokens) == {"plant-01", "plant-02", "plant-03"}

    for raw in tokens.values():
        assert ApiToken.objects.filter(key_hash=hash_token(raw)).exists()


def test_period_labels_roll_over_the_year_boundary():
    call_command("seed_demo", contributors=2, periods=14, verbosity=0)
    labels = list(ReportingPeriod.objects.order_by("starts").values_list("label", flat=True))
    assert labels[0] == "2025-01"
    assert labels[12] == "2026-01"
