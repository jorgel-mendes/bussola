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
