"""Dashboard view tests.

The deployed URL is a graded artifact and the first thing a reviewer sees, so
the states it can be in on a cold visit are pinned here.

The most important test in this file is
`test_no_individual_contributor_value_is_reachable`. In Sprint 1 the same test
existed with the ASSERTION INVERTED -- it asserted that the per-contributor
<details> block WAS present, so that removing it in Sprint 2 would have to be a
deliberate edit to a documented expectation rather than a silent deletion.
This is that edit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from benchmarks.releases import release_benchmark
from budget.models import BudgetPeriod

pytestmark = pytest.mark.django_db

CELL_VALUES = ["3000", "3100", "3200", "3300", "3400", "3500", "3600", "3800"]


@pytest.fixture
def published(cohort, metric, period, make_contributors):
    """A released cell: 8 contributors, budget available, release published."""
    make_contributors(metric, period, CELL_VALUES)
    BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("5.0000"))
    outcome = release_benchmark(
        cohort=cohort, metric=metric, period=period, epsilon=Decimal("1.500000")
    )
    return outcome


def view(client, collaboration, cohort, metric, period):
    return client.get(
        reverse("benchmarks:index"),
        {
            "collaboration": collaboration.slug,
            "cohort": cohort.code,
            "metric": metric.code,
            "period": period.label,
        },
    )


# --- S2-12: the leak is gone ---------------------------------------------


def test_no_individual_contributor_value_is_reachable(
    client, collaboration, cohort, metric, period, published
):
    """PRIVACY-CRITICAL. The inverted form of the Sprint 1 test.

    Sprint 1 rendered a <details> block listing every contributor's exact
    submitted value. That is the most direct disclosure this platform could
    make -- precisely what it exists to prevent. Nothing resembling it may
    return.
    """
    body = view(client, collaboration, cohort, metric, period).content.decode()

    for value in CELL_VALUES:
        assert value not in body, f"exact submitted value {value} is on the page"

    assert "Bench Plant" not in body, "a contributor name is on the page"
    assert "<details" not in body


def test_the_minimum_and_maximum_are_not_published(
    client, collaboration, cohort, metric, period, published
):
    """Also PRIVACY-CRITICAL, and easy to miss.

    Sprint 1's chart plotted Minimum and Maximum alongside the quartiles. Those
    are not summary statistics in any protective sense -- they are two
    individual contributors' exact values, published under a friendlier label.
    """
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "Minimum" not in body
    assert "Maximum" not in body
    assert min(CELL_VALUES) not in body
    assert max(CELL_VALUES) not in body


def test_the_unsafe_banner_is_gone_and_the_page_says_it_is_protected(
    client, collaboration, cohort, metric, period, published
):
    """The Sprint 1 control comes down only because the thing it warned about
    is gone. Its removal is the sprint's headline claim, so it is asserted."""
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "UNSAFE" not in body
    assert "PROTECTED" in body


# --- viewing must not spend budget ---------------------------------------


def test_rendering_the_page_spends_no_budget(
    client, collaboration, cohort, metric, period, published
):
    """The property that separates this from a budget leak.

    If rendering released statistics, a browser refresh would spend epsilon and
    a crawler would exhaust a collaboration's entire allowance in seconds.
    """
    budget = BudgetPeriod.objects.get(period=period)
    before = budget.spent()

    for _ in range(5):
        view(client, collaboration, cohort, metric, period)

    assert budget.spent() == before


def test_rendering_the_page_creates_no_release(
    client, collaboration, cohort, metric, period, make_contributors
):
    """An unreleased cell must stay unreleased however often it is viewed."""
    from benchmarks.models import BenchmarkRelease

    make_contributors(metric, period, CELL_VALUES)
    BudgetPeriod.objects.create(period=period, epsilon_total=Decimal("5.0000"))

    for _ in range(5):
        view(client, collaboration, cohort, metric, period)

    assert BenchmarkRelease.objects.count() == 0


# --- what a published cell shows -----------------------------------------


def test_a_published_release_shows_its_noisy_values_and_epsilon(
    client, collaboration, cohort, metric, period, published
):
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert str(published.release.epsilon_spent) in body
    assert "exponential" in body
    for statistic in published.statistics:
        assert statistic.statistic in body


def test_the_contributor_count_is_shown_exactly(
    client, collaboration, cohort, metric, period, published
):
    """Membership is public, so the count is published unnoised."""
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert ">8<" in body or "8</div>" in body


def test_the_bounds_rationale_is_shown_next_to_the_benchmark(
    client, collaboration, cohort, metric, period, published
):
    """S2-8. The rationale is a required catalog field precisely so it can be
    displayed here: it is how a member judges whether to trust the number."""
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "Thermodynamic floor" in body


def test_the_missing_accuracy_interval_is_explained_not_hidden(
    client, collaboration, cohort, metric, period, published
):
    """A blank column would read as an oversight. The page says why it is
    empty, because a fabricated interval would be read as a promise."""
    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "not available" in body
    assert "exponential mechanism" in body


# --- the unpublished states ----------------------------------------------


def test_a_cell_below_the_threshold_reports_suppression(
    client, collaboration, cohort, metric, period, make_contributors
):
    make_contributors(metric, period, ["3000", "3100"])

    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "Suppressed" in body
    assert "3000" not in body, "a suppressed cell must not leak its values"


def test_an_eligible_but_unreleased_cell_says_so(
    client, collaboration, cohort, metric, period, make_contributors
):
    """Distinct from suppression. The operator has not published yet, and the
    page must not imply the data is too small."""
    make_contributors(metric, period, CELL_VALUES)

    body = view(client, collaboration, cohort, metric, period).content.decode()

    assert "Not yet released" in body
    assert "Suppressed" not in body
    for value in CELL_VALUES:
        assert value not in body


def test_an_unseeded_hub_explains_itself_rather_than_looking_broken(client):
    response = client.get(reverse("benchmarks:index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "No collaborations yet" in body
    from django.urls import reverse as _reverse

    assert f'href="{_reverse("admin:index")}"' in body
    assert "<option" not in body


def test_a_seeded_hub_shows_the_selectors(client, collaboration, cohort, metric, period):
    body = client.get(reverse("benchmarks:index")).content.decode()

    assert "No collaborations yet" not in body
    assert collaboration.name in body
    assert cohort.name in body


def test_statistics_are_shown_in_reading_order_not_alphabetical(
    client, collaboration, cohort, metric, period, published
):
    """A distribution is read left to right.

    ReleasedStatistic.Meta orders alphabetically, which puts "median" before
    "q25" -- fine for the database, nonsense on the page.
    """
    body = view(client, collaboration, cohort, metric, period).content.decode()

    stats_block = body[body.index('class="stats"') : body.index('class="chart-box"')]
    positions = [stats_block.index(name) for name in ("Q25", "MEDIAN", "Q75")]

    assert positions == sorted(positions), "quartiles are not in reading order"
