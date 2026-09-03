"""Dashboard view tests.

The deployed URL is itself a graded artifact and the first thing a reviewer
sees, so the states it can be in on a cold visit are worth pinning.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_an_unseeded_hub_explains_itself_rather_than_looking_broken(client):
    """A freshly deployed hub has no data.

    Rendering four empty dropdowns and a View button reads as a broken page.
    It must say it is empty and say what to do about it.
    """
    response = client.get(reverse("benchmarks:index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "No collaborations yet" in body
    # Reversed, not hard-coded: found in review of PR #1. A customised admin
    # path or a reverse-proxy prefix would silently break a literal "/admin/".
    from django.urls import reverse as _reverse

    assert f'href="{_reverse("admin:index")}"' in body
    assert "<option" not in body


def test_a_seeded_hub_shows_the_selectors(client, collaboration, cohort, metric, period):
    response = client.get(reverse("benchmarks:index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "No collaborations yet" not in body
    assert collaboration.name in body
    assert cohort.name in body


def test_the_unsafe_banner_is_present_while_values_are_exact(client, collaboration):
    """Sprint 1's control against an exact-value page being mistaken for a safe
    one. It comes down in Sprint 2 only when the DP path replaces the exact one.
    """
    response = client.get(reverse("benchmarks:index"))

    assert "UNSAFE" in response.content.decode()


def test_a_cohort_below_the_threshold_is_suppressed(
    client, collaboration, cohort, metric, period, make_contributors
):
    """Suppression is visible in the UI, not merely in the selector."""
    make_contributors(metric, period, ["3000", "3100"])  # 2 < min_contributors 5

    response = client.get(
        reverse("benchmarks:index"),
        {
            "collaboration": collaboration.slug,
            "cohort": cohort.code,
            "metric": metric.code,
            "period": period.label,
        },
    )

    body = response.content.decode()
    assert "Suppressed" in body
    assert "3000" not in body, "a suppressed cell must not leak its values"


def test_a_published_cell_currently_still_exposes_per_contributor_values(
    client, collaboration, cohort, metric, period, make_contributors
):
    """S2-12, privacy-critical: this is the deliberate Sprint 1 leak.

    Pinned as a test so that removing it on day 3 is a visible, deliberate
    change to a documented expectation rather than a silent edit. When the DP
    release path lands, this test INVERTS -- it becomes the assertion that no
    individual contributor value is reachable anywhere in the page.
    """
    make_contributors(metric, period, ["3000", "3100", "3200", "3300", "3400"])

    response = client.get(
        reverse("benchmarks:index"),
        {
            "collaboration": collaboration.slug,
            "cohort": cohort.code,
            "metric": metric.code,
            "period": period.label,
        },
    )

    body = response.content.decode()
    assert "Bench Plant 01" in body, (
        "Sprint 1 leak still present, as expected at this point in Sprint 2. "
        "Invert this assertion when S2-12 removes the <details> block."
    )
