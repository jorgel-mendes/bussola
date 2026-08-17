"""Submission and reporting-period model tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from contributors.models import Contributor
from ingest.models import PeriodStatus, ReportingPeriod, Submission

pytestmark = pytest.mark.django_db


def test_unique_constraint_blocks_duplicate_submissions(contributor, period, metric):
    """INVARIANT (database-enforced): one value per contributor, per period, per metric.

    The API uses update_or_create, but the constraint is what makes the
    invariant true even for a fixture load, a shell session, or a future
    endpoint that forgets.
    """
    Submission.objects.create(
        contributor=contributor, period=period, metric=metric,
        value=Decimal("3400"), n_records=30, agent_version="t",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Submission.objects.create(
            contributor=contributor, period=period, metric=metric,
            value=Decimal("3450"), n_records=30, agent_version="t",
        )


def test_different_contributors_may_submit_same_metric_and_period(
    collaboration, contributor, period, metric, cohort
):
    other = Contributor.objects.create(
        collaboration=collaboration, name="Plant 02", cohort=cohort
    )
    Submission.objects.create(
        contributor=contributor, period=period, metric=metric,
        value=Decimal("3400"), n_records=30, agent_version="t",
    )
    Submission.objects.create(
        contributor=other, period=period, metric=metric,
        value=Decimal("3450"), n_records=30, agent_version="t",
    )
    assert Submission.objects.count() == 2


def test_n_records_must_be_positive(contributor, period, metric):
    with pytest.raises(IntegrityError), transaction.atomic():
        Submission.objects.create(
            contributor=contributor, period=period, metric=metric,
            value=Decimal("3400"), n_records=0, agent_version="t",
        )


def test_clean_rejects_closed_period(contributor, period, metric):
    period.status = PeriodStatus.CLOSED
    period.save(update_fields=["status"])
    submission = Submission(
        contributor=contributor, period=period, metric=metric,
        value=Decimal("3400"), n_records=30, agent_version="t",
    )
    with pytest.raises(ValidationError) as exc:
        submission.clean()
    assert "period" in exc.value.message_dict


def test_clean_rejects_out_of_bounds_value(contributor, period, metric):
    submission = Submission(
        contributor=contributor, period=period, metric=metric,
        value=Decimal("50000"), n_records=30, agent_version="t",
    )
    with pytest.raises(ValidationError) as exc:
        submission.clean()
    assert "value" in exc.value.message_dict


def test_clean_rejects_submission_spanning_collaborations(
    contributor, period, metric, other_collaboration
):
    """INVARIANT: contributor, period and metric must share a collaboration.

    A straddling submission would contaminate another group's benchmark and
    draw down the wrong privacy budget.
    """
    from catalog.models import MetricDefinition

    foreign_metric = MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="foreign_metric",
        name="Foreign",
        unit="x",
        lower_bound=Decimal("0"),
        upper_bound=Decimal("10000"),
        bounds_rationale="Unrelated study.",
    )

    submission = Submission(
        contributor=contributor, period=period, metric=foreign_metric,
        value=Decimal("3400"), n_records=30, agent_version="t",
    )
    with pytest.raises(ValidationError) as exc:
        submission.clean()
    assert "same collaboration" in str(exc.value.message_dict["metric"])


def test_period_end_must_follow_start(collaboration):
    with pytest.raises(IntegrityError), transaction.atomic():
        ReportingPeriod.objects.create(
            collaboration=collaboration,
            label="bad",
            starts=date(2026, 8, 1),
            ends=date(2026, 7, 1),
        )


def test_period_label_unique_per_collaboration_not_globally(
    collaboration, period, other_collaboration
):
    """Two collaborations may both run a period called 2026-07."""
    ReportingPeriod.objects.create(
        collaboration=other_collaboration,
        label="2026-07",
        starts=date(2026, 7, 1),
        ends=date(2026, 8, 1),
    )
    assert ReportingPeriod.objects.filter(label="2026-07").count() == 2

    with pytest.raises(IntegrityError), transaction.atomic():
        ReportingPeriod.objects.create(
            collaboration=collaboration,
            label="2026-07",
            starts=date(2026, 7, 1),
            ends=date(2026, 8, 1),
        )


def test_only_open_periods_accept_submissions(period):
    assert period.accepts_submissions
    for status in (PeriodStatus.CLOSED, PeriodStatus.RELEASED):
        period.status = status
        assert not period.accepts_submissions
