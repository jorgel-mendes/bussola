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

    # Three cohorts, not two. Changed deliberately in Sprint 2: the OpenDP spike
    # measured that a DP quantile needs roughly 50 contributors at epsilon=1 to
    # beat the sector IQR, so the demo now carries two cohorts large enough for
    # the benchmark to mean something and one small enough to show what happens
    # when it cannot. See test_cohorts_are_split_unevenly_on_purpose below.
    assert Cohort.objects.count() == 3
    assert Contributor.objects.count() == 6
    assert MetricDefinition.objects.count() == 2
    assert ReportingPeriod.objects.count() == 3
    assert ApiToken.objects.active().count() == 6


def test_cohorts_are_split_unevenly_on_purpose():
    """The demo must contain a cohort too small to benchmark.

    An even split cannot express "this cell cannot support a release", which is
    the case the privacy story most needs to demonstrate -- and the harder half
    to fake. At the demo size the small cohort produced q75 BELOW q25, which is
    the noise exceeding the signal, visibly.
    """
    call_command("seed_demo", contributors=106, periods=1, verbosity=0)

    sizes = sorted(c.contributors.count() for c in Cohort.objects.all())

    assert sizes == [6, 50, 50], f"expected a 50/50/6 split, got {sizes}"


def test_the_seeded_split_matches_datagen():
    """seed_demo and datagen must agree about who is in which cohort.

    They are separate programs with separate copies of the weights. If they
    drift, the seeded roster and the generated CSVs describe different
    consortia, and every benchmark is computed over the wrong cohort.
    """
    import importlib.util
    import sys
    from pathlib import Path

    # Loaded from its path under a private name, and unregistered afterwards.
    #
    # The obvious version -- sys.path.insert then `import generate` -- leaks the
    # path into every later test in the process, which is what Copilot flagged.
    # It also caches the module under a name a later import would reuse, and
    # that bit me for real earlier in this sprint: after editing
    # datagen/generate.py the test kept reading the previous version, so a
    # correctly restored file looked broken.
    #
    # The module IS registered in sys.modules before execution, briefly and
    # under a private name. That is not optional: @dataclass resolves its type
    # hints through sys.modules[cls.__module__], and generate.py defines
    # dataclasses, so executing it unregistered fails with a bare AttributeError
    # from inside the stdlib.
    datagen = Path(__file__).resolve().parents[2] / "datagen" / "generate.py"
    spec = importlib.util.spec_from_file_location("_datagen_generate", datagen)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        datagen_weights = module.COHORT_WEIGHTS
    finally:
        sys.modules.pop(spec.name, None)

    from contributors.management.commands.seed_demo import COHORT_WEIGHTS as SEED_WEIGHTS

    assert datagen_weights == SEED_WEIGHTS


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
