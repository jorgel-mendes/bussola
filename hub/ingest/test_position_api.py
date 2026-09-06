"""Contributor position API tests (S3-1).

The privacy invariants this endpoint must hold, and which each test names:

1. IT SPENDS NOTHING. Placing your own value against an already-published
   release is post-processing. If reading released statistics, an agent polling
   from cron would drain its collaboration's budget overnight.
2. IT REVEALS NO EXACT VALUE. Only the noisy released quartiles, and the
   caller's own submission — which is the caller's own data.
3. THE COHORT COMES FROM THE TOKEN. A member cannot ask where it would sit in
   a cohort it does not belong to.
4. AN UNUSABLE RELEASE IS REFUSED, not sorted into something presentable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from benchmarks.models import BenchmarkRelease, ReleasedStatistic
from budget.models import LedgerEntry
from ingest.models import Submission

pytestmark = pytest.mark.django_db

URL = "ingest:contributor-position"


@pytest.fixture
def released(release):
    """An ordered, usable release: q25=3000, median=3400, q75=3800."""
    for statistic, value in (("q25", "3000"), ("median", "3400"), ("q75", "3800")):
        ReleasedStatistic.objects.create(
            release=release,
            statistic=statistic,
            mechanism="exponential",
            value=Decimal(value),
            epsilon_spent=Decimal("0.333334"),
        )
    return release


@pytest.fixture
def own_submission(contributor, metric, period):
    return Submission.objects.create(
        contributor=contributor,
        period=period,
        metric=metric,
        value=Decimal("3100.000000"),
        n_records=30,
        agent_version="test",
    )


def URL_of(metric, period) -> str:
    return f"{reverse(URL)}?metric={metric.code}&period={period.label}"


# --- the invariant that matters most ---------------------------------------


def test_reading_a_position_spends_no_privacy_budget(
    auth_api, metric, period, released, own_submission
):
    """INVARIANT 1. Post-processing, so nothing may be charged.

    Ten reads, which is what a cron would do. If this endpoint released
    anything, the ledger would grow and the collaboration's budget would be
    consumed by members looking at their own dashboards.
    """
    entries_before = LedgerEntry.objects.count()
    releases_before = BenchmarkRelease.objects.count()

    for _ in range(10):
        assert auth_api.get(URL_of(metric, period)).status_code == 200

    assert LedgerEntry.objects.count() == entries_before
    assert BenchmarkRelease.objects.count() == releases_before


def test_response_carries_no_exact_cohort_statistic(
    auth_api, metric, period, released, own_submission, make_contributors
):
    """INVARIANT 2. The exact quartiles of the cohort must not appear.

    The cohort's true values are seeded here so that an accidental exact
    computation would produce something recognisably different from the
    released numbers, and be caught.
    """
    make_contributors(metric, period, ["3010", "3020", "3030", "3040", "3050"])

    body = auth_api.get(URL_of(metric, period)).json()

    assert body["released_q25"] == "3000.000000"
    assert body["released_median"] == "3400.000000"
    assert body["released_q75"] == "3800.000000"
    # Only the caller's own value is echoed back.
    assert body["your_value"] == "3100.000000"


def test_places_the_contributor_in_the_right_quartile(
    auth_api, metric, period, released, own_submission
):
    """3100 sits between q25=3000 and median=3400, so Q2."""
    body = auth_api.get(URL_of(metric, period)).json()

    assert body["quartile"] == "Q2"
    assert body["is_usable"] is True
    assert body["cohort_code"] and body["metric_unit"]


def test_the_usable_answer_still_says_the_boundaries_are_noisy(
    auth_api, metric, period, released, own_submission
):
    """A quartile presented without that caveat would be read as exact."""
    body = auth_api.get(URL_of(metric, period)).json()

    assert "differentially private" in body["caveat"]


# --- INVARIANT 4: the unusable release --------------------------------------


def test_an_out_of_order_release_refuses_to_place_the_contributor(
    auth_api, metric, period, release, own_submission
):
    """The Sprint 2 finding, enforced at the member-facing surface.

    q75 below q25 is what a six-contributor cohort produced on the deployed
    hub. There is no defensible quartile to report from it, and sorting the
    triple first would produce one — privacy-safe, and worse, because the
    member would act on it.
    """
    for statistic, value in (("q25", "3800"), ("median", "3400"), ("q75", "3000")):
        ReleasedStatistic.objects.create(
            release=release,
            statistic=statistic,
            mechanism="exponential",
            value=Decimal(value),
            epsilon_spent=Decimal("0.333334"),
        )

    body = auth_api.get(URL_of(metric, period)).json()

    assert body["quartile"] == "unknown"
    assert body["is_usable"] is False
    assert "too noisy" in body["caveat"]
    # And the released values are still returned, so the member can see WHY.
    assert body["released_q25"] == "3800.000000"
    assert body["released_q75"] == "3000.000000"


# --- INVARIANT 3: tenancy ---------------------------------------------------


def test_another_collaborations_metric_is_not_reachable(
    auth_api, period, other_collaboration, released, own_submission
):
    """Indistinguishable from a metric that does not exist — deliberately."""
    from catalog.models import MetricDefinition

    foreign = MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="foreign_metric",
        name="Foreign",
        unit="x",
        lower_bound=Decimal("0"),
        upper_bound=Decimal("100"),
        bounds_rationale="Another group's metric.",
        statistics=["q25", "median", "q75"],
    )

    response = auth_api.get(f"{reverse(URL)}?metric={foreign.code}&period={period.label}")

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_metric"


def test_a_contributor_sees_only_its_own_cohorts_release(
    auth_api, collaboration, metric, period, released, own_submission, contributor
):
    """The cohort comes from the token.

    A second cohort with its own release exists; the caller must get its own,
    and there is no parameter through which it could ask for the other.
    """
    from collaborations.models import Cohort

    other_cohort = Cohort.objects.create(
        collaboration=collaboration, code="9999", name="Another cohort"
    )
    other_release = BenchmarkRelease.objects.create(
        period=period, cohort=other_cohort, metric=metric, n_contributors=40,
        epsilon_spent=Decimal("1.000000"),
    )
    for statistic, value in (("q25", "10"), ("median", "20"), ("q75", "30")):
        ReleasedStatistic.objects.create(
            release=other_release, statistic=statistic, mechanism="exponential",
            value=Decimal(value), epsilon_spent=Decimal("0.333334"),
        )

    body = auth_api.get(URL_of(metric, period)).json()

    assert body["cohort_code"] == contributor.cohort.code != other_cohort.code
    assert body["released_q25"] == "3000.000000"


def test_requires_a_token(api, metric, period, released):
    assert api.get(URL_of(metric, period)).status_code == 401


# --- refusals that say what to do -------------------------------------------


def test_404_when_the_contributor_has_not_submitted(auth_api, metric, period, released):
    response = auth_api.get(URL_of(metric, period))

    assert response.status_code == 404
    assert response.json()["code"] == "not_submitted"
    assert "not submitted" in response.json()["detail"]


def test_404_when_nothing_has_been_published(auth_api, metric, period, own_submission):
    """Covers both 'not released yet' and 'suppressed for too few contributors'.

    They are deliberately one message: distinguishing them would tell a member
    how many contributors its cohort has, which is exactly what suppression
    exists to withhold.
    """
    response = auth_api.get(URL_of(metric, period))

    assert response.status_code == 404
    assert response.json()["code"] == "not_published"
    detail = response.json()["detail"]
    assert "Nothing has been published" in detail
    assert "too few contributors" in detail


def test_404_when_the_release_is_missing_a_quantile(
    auth_api, metric, period, release, own_submission
):
    """A partial release cannot support a quartile, and must not pretend to."""
    ReleasedStatistic.objects.create(
        release=release, statistic="median", mechanism="exponential",
        value=Decimal("3400"), epsilon_spent=Decimal("0.333334"),
    )

    response = auth_api.get(URL_of(metric, period))

    assert response.status_code == 404
    assert response.json()["code"] == "incomplete_release"
    assert "q25" in response.json()["detail"]


def test_400_when_parameters_are_missing(auth_api):
    response = auth_api.get(reverse(URL))

    assert response.status_code == 400
    assert response.json()["code"] == "missing_parameter"
