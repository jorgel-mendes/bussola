"""Tests for `manage.py load_submissions` — retro action B2.

Zero coverage at the end of Sprint 2, like `release_period`.

THE CLAIM THIS COMMAND MAKES, and which these tests exist to hold it to: the
aggregates it loads are *exactly what the agent would have computed from the
same CSV*. The demo depends on that. A few contributors submit through the real
network path and the rest are loaded here, and the demo says so out loud — which
is only honest if the two paths genuinely agree. If this command computed
something else, the benchmark would be published over a mixture of two different
statistics, and the demo's central claim would be false while looking fine.

The second claim is the bounds rule: an out-of-range aggregate is REFUSED, never
clamped, exactly as the API refuses it. Clamping would hide a unit-conversion
fault behind a plausible number.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contributors.models import Contributor
from ingest.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def contributors(collaboration, cohort):
    """Named so `_slug` maps them onto the datagen directory names."""
    return [
        Contributor.objects.create(
            collaboration=collaboration, name=f"Plant {i:02d}", cohort=cohort
        )
        for i in (1, 2)
    ]


def write_csv(data_dir, plant, metric_code, rows):
    plant_dir = data_dir / plant
    plant_dir.mkdir(parents=True, exist_ok=True)
    path = plant_dir / f"{metric_code}.csv"
    path.write_text(
        "period,day,value\n" + "".join(f"{p},{d},{v}\n" for p, d, v in rows),
        encoding="utf-8",
    )
    return path


def run(collaboration, data_dir, **kwargs):
    out = io.StringIO()
    call_command(
        "load_submissions",
        collaboration=collaboration.slug,
        data_dir=data_dir,
        stdout=out,
        **kwargs,
    )
    return out.getvalue()


# --- the claim the demo rests on -------------------------------------------


def test_it_loads_the_mean_the_agent_would_have_submitted(
    collaboration, metric, period, contributors, tmp_path
):
    """The mean of that period's daily records — the agent's own computation.

    3000, 3200 and 3400 average to 3200. If this command took a median, a last
    value, or a sum, the demo would publish a benchmark over two different
    statistics and say nothing about it.
    """
    write_csv(tmp_path, "plant-01", metric.code, [
        (period.label, 1, "3000"), (period.label, 2, "3200"), (period.label, 3, "3400"),
    ])

    run(collaboration, tmp_path, period=period.label)

    submission = Submission.objects.get(contributor__name="Plant 01")
    assert submission.value == Decimal("3200.000000")
    assert submission.n_records == 3


def test_the_loaded_value_matches_the_agent_s_own_function_exactly(
    collaboration, metric, period, contributors, tmp_path
):
    """Asserted against the agent's code, not against a number I computed.

    A hand-written expected value drifts the moment either side changes its
    rounding. This compares the two implementations that are claimed to agree.
    """
    import polars as pl

    from bussola_agent.compute import local_mean

    values = ["3011.5", "3199.25", "3410.75", "2988.5"]
    write_csv(tmp_path, "plant-01", metric.code,
              [(period.label, i, v) for i, v in enumerate(values, start=1)])

    run(collaboration, tmp_path, period=period.label)

    agent_value = local_mean(pl.Series([float(v) for v in values]))
    loaded = Submission.objects.get(contributor__name="Plant 01").value
    assert loaded == agent_value.quantize(Decimal("0.000001"))


# --- the bounds rule, shared with the API ----------------------------------


def test_an_out_of_bounds_aggregate_is_refused_not_clamped(
    collaboration, metric, period, contributors, tmp_path
):
    """Same rule as the ingestion API. Clamping would hide a unit-conversion
    fault behind a plausible number, and the operator would never learn."""
    write_csv(tmp_path, "plant-01", metric.code, [(period.label, 1, "99999")])

    output = run(collaboration, tmp_path, period=period.label)

    assert Submission.objects.count() == 0
    assert "refused" in output
    assert "1 refused as out of bounds" in output


def test_a_refusal_does_not_stop_the_other_contributors(
    collaboration, metric, period, contributors, tmp_path
):
    """One bad CSV must not cost the whole load."""
    write_csv(tmp_path, "plant-01", metric.code, [(period.label, 1, "99999")])
    write_csv(tmp_path, "plant-02", metric.code, [(period.label, 1, "3200")])

    run(collaboration, tmp_path, period=period.label)

    assert Submission.objects.count() == 1
    assert Submission.objects.get().contributor.name == "Plant 02"


# --- --skip, which exists to protect the sensitivity bound ------------------


def test_skipped_contributors_are_left_for_the_real_agent(
    collaboration, metric, period, contributors, tmp_path
):
    """The contributors submitting over the network must not be loaded here.

    Not merely tidiness: a contributor whose aggregate arrives twice would have
    its loaded value overwrite the agent's real submission, and the demo would
    be showing a benchmark that did not include the data it just watched being
    submitted.
    """
    write_csv(tmp_path, "plant-01", metric.code, [(period.label, 1, "3200")])
    write_csv(tmp_path, "plant-02", metric.code, [(period.label, 1, "3300")])

    output = run(collaboration, tmp_path, period=period.label, skip=["plant-01"])

    assert Submission.objects.count() == 1
    assert Submission.objects.get().contributor.name == "Plant 02"
    assert "1 contributors skipped" in output


def test_loading_twice_does_not_double_a_contributor_s_weight(
    collaboration, metric, period, contributors, tmp_path
):
    """Idempotent, for the reason the API is idempotent: a contributor counted
    twice breaks the per-contributor sensitivity bound the guarantee rests on.
    """
    write_csv(tmp_path, "plant-01", metric.code, [(period.label, 1, "3200")])

    run(collaboration, tmp_path, period=period.label)
    run(collaboration, tmp_path, period=period.label)

    assert Submission.objects.count() == 1


# --- period selection -------------------------------------------------------


def test_only_the_requested_period_is_loaded(
    collaboration, metric, period, contributors, tmp_path
):
    write_csv(tmp_path, "plant-01", metric.code, [
        (period.label, 1, "3200"), ("2020-01", 1, "3300"),
    ])

    run(collaboration, tmp_path, period=period.label)

    assert Submission.objects.count() == 1
    assert Submission.objects.get().period == period


def test_a_period_the_hub_does_not_know_is_ignored_not_invented(
    collaboration, metric, period, contributors, tmp_path
):
    """Data can carry periods the collaboration never opened. Creating them
    here would let a CSV define the reporting calendar."""
    write_csv(tmp_path, "plant-01", metric.code, [("2020-01", 1, "3200")])

    run(collaboration, tmp_path)

    assert Submission.objects.count() == 0


def test_a_directory_with_no_matching_contributor_is_ignored(
    collaboration, metric, period, contributors, tmp_path
):
    """datagen may hold more plants than this collaboration registered."""
    write_csv(tmp_path, "plant-99", metric.code, [(period.label, 1, "3200")])

    run(collaboration, tmp_path, period=period.label)

    assert Submission.objects.count() == 0


# --- refusals ---------------------------------------------------------------


def test_a_missing_data_directory_is_refused_with_the_fix(collaboration, tmp_path):
    with pytest.raises(CommandError, match="Run datagen first"):
        run(collaboration, tmp_path / "does-not-exist")


def test_an_unknown_period_is_refused(collaboration, metric, contributors, tmp_path):
    (tmp_path / "plant-01").mkdir()
    with pytest.raises(CommandError, match="No period"):
        run(collaboration, tmp_path, period="1999-01")


def test_an_unknown_collaboration_is_refused(tmp_path):
    out = io.StringIO()
    with pytest.raises(CommandError, match="No active collaboration"):
        call_command(
            "load_submissions", collaboration="not-a-real-slug",
            data_dir=tmp_path, stdout=out,
        )
