"""Ingestion API tests.

The idempotency, authentication and tenancy tests here protect privacy
invariants, not just correctness. Each one names the invariant it defends so
that a future change which breaks it fails with an explanation rather than a
red dot.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from contributors.models import ApiToken, Contributor
from ingest.models import PeriodStatus, Submission

pytestmark = pytest.mark.django_db


def payload(**overrides) -> dict:
    base = {
        "metric_code": "specific_thermal_energy",
        "period_label": "2026-07",
        "value": "3400.000000",
        "n_records": 30,
        "agent_version": "0.1.0",
    }
    base.update(overrides)
    return base


# --- authentication --------------------------------------------------------


def test_rejects_request_without_token(api, metric, period):
    response = api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 401


def test_rejects_unknown_token(api, metric, period):
    api.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    response = api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 401


def test_rejects_revoked_token(api, metric, period, token_pair):
    token, raw = token_pair
    token.revoke()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 401


def test_rejects_token_of_inactive_contributor(api, metric, period, token_pair, contributor):
    _token, raw = token_pair
    contributor.is_active = False
    contributor.save(update_fields=["is_active"])
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 401


def test_rejects_token_of_inactive_collaboration(
    api, metric, period, token_pair, collaboration
):
    """Deactivating a collaboration must stop its agents immediately.

    Otherwise a wound-down consortium keeps accepting data nobody is governing.
    """
    _token, raw = token_pair
    collaboration.is_active = False
    collaboration.save(update_fields=["is_active"])
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 401


def test_raw_token_is_never_stored(token_pair):
    """A database dump must not yield usable credentials."""
    token, raw = token_pair
    assert raw not in ApiToken.objects.values_list("key_hash", flat=True)
    assert token.key_hash != raw
    assert len(token.key_hash) == 64


def test_successful_call_stamps_last_used(auth_api, metric, period, token_pair):
    token, _raw = token_pair
    assert token.last_used_at is None
    auth_api.post(reverse("ingest:submission-create"), payload(), format="json")
    token.refresh_from_db()
    assert token.last_used_at is not None


# --- contributor identity --------------------------------------------------


def test_contributor_is_taken_from_token_not_body(
    auth_api, metric, period, contributor, collaboration, cohort
):
    """INVARIANT: an agent cannot submit on another contributor's behalf.

    The payload has no contributor field at all; even if a caller injects one,
    the submission must be attributed to the token's contributor.
    """
    other = Contributor.objects.create(
        collaboration=collaboration, name="Someone Else", cohort=cohort
    )
    response = auth_api.post(
        reverse("ingest:submission-create"),
        payload(contributor=other.pk, contributor_id=other.pk),
        format="json",
    )
    assert response.status_code == 201
    assert Submission.objects.get().contributor == contributor


# --- tenancy boundary ------------------------------------------------------


def test_cannot_submit_against_another_collaborations_metric(
    auth_api, metric, period, other_collaboration
):
    """INVARIANT: an agent is confined to its own collaboration.

    A metric code that exists only in another collaboration must resolve to
    "unknown" -- not merely be refused, but be indistinguishable from a code
    that does not exist at all, so the response does not reveal what other
    groups measure.
    """
    from catalog.models import MetricDefinition

    MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="secret_metric",
        name="Another group's metric",
        unit="x",
        lower_bound=Decimal("0"),
        upper_bound=Decimal("1000"),
        bounds_rationale="Unrelated study.",
    )

    response = auth_api.post(
        reverse("ingest:submission-create"), payload(metric_code="secret_metric"), format="json"
    )
    assert response.status_code == 400
    assert "Unknown or inactive metric" in str(response.json())
    assert not Submission.objects.exists()


def test_cannot_submit_against_another_collaborations_period(
    auth_api, metric, period, other_collaboration
):
    from datetime import date

    from ingest.models import ReportingPeriod

    ReportingPeriod.objects.create(
        collaboration=other_collaboration,
        label="2099-12",
        starts=date(2099, 12, 1),
        ends=date(2100, 1, 1),
    )

    response = auth_api.post(
        reverse("ingest:submission-create"), payload(period_label="2099-12"), format="json"
    )
    assert response.status_code == 400
    assert not Submission.objects.exists()


def test_metric_list_shows_only_own_collaboration(auth_api, metric, other_collaboration):
    """Enumerating the catalog must not leak what other groups measure."""
    from catalog.models import MetricDefinition

    MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="secret_metric",
        name="Another group's metric",
        unit="x",
        lower_bound=Decimal("0"),
        upper_bound=Decimal("1000"),
        bounds_rationale="Unrelated study.",
    )

    codes = [item["code"] for item in auth_api.get(reverse("ingest:metric-list")).json()]
    assert codes == ["specific_thermal_energy"]


def test_same_metric_code_may_exist_in_two_collaborations(
    auth_api, metric, period, other_collaboration
):
    """Codes are unique per collaboration, not globally.

    Two groups may both measure "specific_thermal_energy" with different bounds and
    different rationales, and each must see only its own.
    """
    from catalog.models import MetricDefinition

    MetricDefinition.objects.create(
        collaboration=other_collaboration,
        code="specific_thermal_energy",
        name="Same code elsewhere",
        unit="kWh/t",
        lower_bound=Decimal("1"),
        upper_bound=Decimal("2"),
        bounds_rationale="Different bounds entirely.",
    )

    response = auth_api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 201
    assert Submission.objects.get().metric == metric


# --- idempotency (privacy invariant) ---------------------------------------


def test_resubmission_updates_in_place(auth_api, metric, period, contributor):
    """INVARIANT: one contributor contributes at most one value per (period, metric).

    Without this, a contributor could submit twice and double its weight in the
    aggregate, breaking the per-contributor sensitivity bound that the whole
    privacy guarantee rests on.
    """
    url = reverse("ingest:submission-create")

    first = auth_api.post(url, payload(value="3400.000000"), format="json")
    assert first.status_code == 201
    assert first.json()["created"] is True

    second = auth_api.post(url, payload(value="3255.000000"), format="json")
    assert second.status_code == 200
    assert second.json()["created"] is False

    assert Submission.objects.count() == 1
    assert Submission.objects.get().value == Decimal("3255.000000")


# --- validation ------------------------------------------------------------


def test_rejects_value_above_upper_bound(auth_api, metric, period):
    response = auth_api.post(
        reverse("ingest:submission-create"), payload(value="9000.000000"), format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "value_out_of_bounds"
    assert Submission.objects.count() == 0


def test_rejects_value_below_lower_bound(auth_api, metric, period):
    response = auth_api.post(
        reverse("ingest:submission-create"), payload(value="500.000000"), format="json"
    )
    assert response.status_code == 422
    assert Submission.objects.count() == 0


def test_out_of_bounds_value_is_rejected_not_clamped(auth_api, metric, period):
    """Clamping would hide a sensor or unit fault behind a plausible number."""
    auth_api.post(reverse("ingest:submission-create"), payload(value="9000.0"), format="json")
    assert not Submission.objects.exists()


def test_rejects_submission_to_closed_period(auth_api, metric, period):
    period.status = PeriodStatus.CLOSED
    period.save(update_fields=["status"])
    response = auth_api.post(reverse("ingest:submission-create"), payload(), format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "period_not_open"


def test_rejects_unknown_metric(auth_api, metric, period):
    response = auth_api.post(
        reverse("ingest:submission-create"), payload(metric_code="not_a_metric"), format="json"
    )
    assert response.status_code == 400


def test_rejects_unknown_period(auth_api, metric, period):
    response = auth_api.post(
        reverse("ingest:submission-create"), payload(period_label="1999-01"), format="json"
    )
    assert response.status_code == 400


def test_rejects_zero_records(auth_api, metric, period):
    response = auth_api.post(
        reverse("ingest:submission-create"), payload(n_records=0), format="json"
    )
    assert response.status_code == 400


# --- catalog ---------------------------------------------------------------


def test_metric_list_exposes_bounds_and_rationale(auth_api, metric):
    response = auth_api.get(reverse("ingest:metric-list"))
    assert response.status_code == 200
    item = response.json()[0]
    assert item["code"] == "specific_thermal_energy"
    assert item["bounds_rationale"]
    assert Decimal(item["lower_bound"]) == metric.lower_bound


def test_healthz_needs_no_auth(api):
    assert api.get(reverse("ingest:healthz")).status_code == 200
