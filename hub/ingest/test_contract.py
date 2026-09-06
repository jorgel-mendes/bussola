"""Contract test: agent DTO <-> hub serializer.

The agent and the hub are separate programs that ship independently. This test
is the only thing standing between them and a silent wire-format drift, so it
asserts the *shape* of the contract, not just that one example round-trips.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from bussola_contracts import CONTRACT_VERSION, MetricSpec, SubmissionAck, SubmissionPayload
from ingest.serializers import SubmissionCreateSerializer

pytestmark = pytest.mark.django_db


def test_agent_payload_fields_match_serializer_fields():
    """Every field the agent sends must be one the hub knows about."""
    payload_fields = set(SubmissionPayload.model_fields)
    serializer_fields = set(SubmissionCreateSerializer().fields)
    unknown = payload_fields - serializer_fields
    assert not unknown, f"Agent sends fields the hub does not accept: {sorted(unknown)}"


def test_serializer_required_fields_are_all_produced_by_the_agent():
    """And every field the hub requires must be one the agent sends."""
    required = {
        name for name, field in SubmissionCreateSerializer().fields.items() if field.required
    }
    missing = required - set(SubmissionPayload.model_fields)
    assert not missing, f"Hub requires fields the agent never sends: {sorted(missing)}"


def test_agent_payload_is_accepted_by_the_hub_serializer(collaboration, metric, period):
    payload = SubmissionPayload(
        metric_code="specific_thermal_energy",
        period_label="2026-07",
        value=Decimal("3400.0"),
        n_records=30,
        agent_version="0.1.0",
    )
    serializer = SubmissionCreateSerializer(
        data=payload.model_dump(mode="json"), context={"collaboration": collaboration}
    )
    assert serializer.is_valid(), serializer.errors


def test_ack_field_names_match_the_hub_serializer():
    """Structural check on the response contract too, not just the request.

    The rename from `plant` to `contributor` broke exactly this boundary, so it
    is now asserted rather than discovered at runtime.
    """
    from ingest.serializers import SubmissionAckSerializer

    ack_fields = set(SubmissionAck.model_fields)
    serializer_fields = set(SubmissionAckSerializer().fields)
    assert ack_fields == serializer_fields, (
        f"Agent expects {sorted(ack_fields)}, hub returns {sorted(serializer_fields)}"
    )


def test_hub_response_validates_against_agent_ack_model(auth_api, metric, period):
    """A real HTTP response must parse into the agent's SubmissionAck."""
    payload = SubmissionPayload(
        metric_code="specific_thermal_energy",
        period_label="2026-07",
        value=Decimal("3400.0"),
        n_records=30,
        agent_version="0.1.0",
    )
    response = auth_api.post(
        reverse("ingest:submission-create"), payload.model_dump(mode="json"), format="json"
    )
    assert response.status_code == 201
    ack = SubmissionAck.model_validate(response.json())
    assert ack.metric_code == "specific_thermal_energy"
    assert ack.created is True


def test_metric_endpoint_validates_against_agent_metric_spec(auth_api, metric):
    """The agent parses the catalog with MetricSpec; the hub must satisfy it."""
    response = auth_api.get(reverse("ingest:metric-list"))
    specs = [MetricSpec.model_validate(item) for item in response.json()]
    assert specs[0].code == "specific_thermal_energy"
    assert specs[0].bounds_rationale


def test_payload_quantises_value_to_stored_precision():
    """The agent must not send more precision than the column holds.

    Otherwise the stored value differs from the sent value, and the idempotency
    check on resubmission compares against something the agent never sent.
    """
    payload = SubmissionPayload(
        metric_code="m",
        period_label="2026-07",
        value=Decimal("412.1234567890"),
        n_records=1,
        agent_version="0.1.0",
    )
    assert payload.value == Decimal("412.123457")


def test_contract_version_is_pinned():
    assert CONTRACT_VERSION == "1.0"
    assert SubmissionPayload(
        metric_code="m", period_label="p", value=Decimal("1"),
        n_records=1, agent_version="0.1.0",
    ).contract_version == "1.0"


# --- the position report (S3-1) --------------------------------------------
#
# The position endpoint hand-builds its response dict rather than going through
# a DRF serializer, so there is no serializer for a structural test to compare
# against. The live response is compared to the pydantic model instead, which is
# a stronger check: it validates the actual bytes an agent will parse.


def test_position_response_validates_against_the_agent_contract(
    auth_api, metric, period, cohort, contributor
):
    """The hub's response must be parseable by `PositionReport`, exactly.

    `model_validate` on a frozen model with no extra fields allowed would pass a
    response missing an optional field, so the field sets are compared too. The
    plant/contributor rename broke this boundary once already.
    """
    from decimal import Decimal

    from benchmarks.models import BenchmarkRelease, ReleasedStatistic
    from bussola_contracts import PositionReport
    from ingest.models import Submission

    Submission.objects.create(
        contributor=contributor, period=period, metric=metric,
        value=Decimal("3100.000000"), n_records=30, agent_version="test",
    )
    release = BenchmarkRelease.objects.create(
        period=period, cohort=cohort, metric=metric, n_contributors=8,
        epsilon_spent=Decimal("1.000000"),
    )
    for statistic, value in (("q25", "3000"), ("median", "3400"), ("q75", "3800")):
        ReleasedStatistic.objects.create(
            release=release, statistic=statistic, mechanism="exponential",
            value=Decimal(value), epsilon_spent=Decimal("0.333334"),
        )

    body = auth_api.get(
        f"{reverse('ingest:contributor-position')}?metric={metric.code}&period={period.label}"
    ).json()

    report = PositionReport.model_validate(body)

    assert report.quartile == "Q2"
    assert report.contract_version == CONTRACT_VERSION
    assert set(body) == set(PositionReport.model_fields), (
        "Hub response and PositionReport have drifted apart: "
        f"hub-only={sorted(set(body) - set(PositionReport.model_fields))}, "
        f"contract-only={sorted(set(PositionReport.model_fields) - set(body))}"
    )
