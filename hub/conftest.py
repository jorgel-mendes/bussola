"""Shared pytest fixtures for hub tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog.models import MetricDefinition, Statistic
from collaborations.models import Cohort, Collaboration, OperatorKind
from contributors.models import ApiToken, Contributor
from ingest.models import PeriodStatus, ReportingPeriod


@pytest.fixture
def collaboration(db) -> Collaboration:
    return Collaboration.objects.create(
        slug="demo",
        name="Demo Benchmark",
        operator_name="Demo Federation",
        operator_kind=OperatorKind.ASSOCIATION,
        min_contributors=5,
    )


@pytest.fixture
def cohort(db, collaboration) -> Cohort:
    return Cohort.objects.create(
        collaboration=collaboration, code="2320", name="Cement and lime"
    )


@pytest.fixture
def metric(db, collaboration) -> MetricDefinition:
    return MetricDefinition.objects.create(
        collaboration=collaboration,
        code="specific_thermal_energy",
        name="Specific thermal energy consumption",
        unit="MJ/t clinker",
        lower_bound=Decimal("1760.000000"),
        upper_bound=Decimal("7100.000000"),
        bounds_rationale=(
            "Thermodynamic floor (reaction enthalpy of clinker formation, "
            "+1 761 kJ/kg) and wet-kiln ceiling. See docs/REFERENCES.md."
        ),
        # One submitted aggregate per contributor per period => one row in the
        # table the hub runs DP over. NOT the observation count.
        contributions_per_period=1,
        statistics=[Statistic.COUNT, Statistic.Q25, Statistic.MEDIAN, Statistic.Q75],
    )


@pytest.fixture
def period(db, collaboration) -> ReportingPeriod:
    return ReportingPeriod.objects.create(
        collaboration=collaboration,
        label="2026-07",
        starts=date(2026, 7, 1),
        ends=date(2026, 8, 1),
        status=PeriodStatus.OPEN,
    )


@pytest.fixture
def contributor(db, collaboration, cohort) -> Contributor:
    return Contributor.objects.create(
        collaboration=collaboration, name="Plant 01", cohort=cohort
    )


@pytest.fixture
def token_pair(db, contributor) -> tuple[ApiToken, str]:
    return ApiToken.issue(contributor, label="test")


@pytest.fixture
def api(db) -> APIClient:
    return APIClient()


@pytest.fixture
def auth_api(db, token_pair) -> APIClient:
    _token, raw = token_pair
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


@pytest.fixture
def other_collaboration(db) -> Collaboration:
    """A second, unrelated collaboration.

    Used to prove the tenancy boundary holds: one collaboration's agent must not
    see or submit against another's metrics.
    """
    return Collaboration.objects.create(
        slug="other",
        name="Unrelated Study",
        operator_name="Some University",
        operator_kind=OperatorKind.UNIVERSITY,
        min_contributors=5,
    )


@pytest.fixture
def make_contributors(db, collaboration, cohort):
    """Create N contributors each with a submission, for benchmark tests."""

    def _make(metric, period, values: list[str]):
        from ingest.models import Submission

        made = []
        for i, value in enumerate(values, start=1):
            c = Contributor.objects.create(
                collaboration=collaboration, name=f"Bench Plant {i:02d}", cohort=cohort
            )
            Submission.objects.create(
                contributor=c,
                period=period,
                metric=metric,
                value=Decimal(value),
                n_records=30,
                agent_version="test",
            )
            made.append(c)
        return made

    return _make
