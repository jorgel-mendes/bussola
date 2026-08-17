"""Hub client tests.

The important assertions here are about the *retryable* flag. An agent running
unattended from cron needs to distinguish "try again in an hour" from "a human
must look at this", and that distinction is carried by status code.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from bussola_agent.client import HubClient, HubError
from bussola_agent.config import AgentConfig
from bussola_contracts import SubmissionPayload

CONFIG = AgentConfig(hub_url="https://hub.example", token="tok", contributor_label="plant-01")

METRIC_JSON = [
    {
        "code": "specific_thermal_energy",
        "name": "Specific thermal energy",
        "unit": "MJ/t clinker",
        "value_type": "continuous",
        "lower_bound": "1760.000000",
        "upper_bound": "7100.000000",
        "bounds_rationale": "Thermodynamic floor (reaction enthalpy) and wet-kiln ceiling.",
        "contributions_per_period": 1,
        "statistics": ["median"],
    }
]

PAYLOAD = SubmissionPayload(
    metric_code="specific_thermal_energy",
    period_label="2026-07",
    value=Decimal("3400.0"),
    n_records=30,
    agent_version="0.1.0",
)


@respx.mock
def test_fetch_metric_returns_spec():
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    with HubClient(CONFIG) as client:
        spec = client.fetch_metric("specific_thermal_energy")
    assert spec.unit == "MJ/t clinker"
    assert spec.lower_bound == Decimal("1760.000000")


@respx.mock
def test_fetch_metric_lists_known_codes_when_missing():
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError, match="specific_thermal_energy"):
        client.fetch_metric("not_a_metric")


@respx.mock
def test_sends_bearer_token():
    route = respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 1, "created": True, "contributor": "Plant 01",
                "metric_code": "specific_thermal_energy", "period_label": "2026-07",
                "value": "3400.000000",
            },
        )
    )
    with HubClient(CONFIG) as client:
        client.submit(PAYLOAD)
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_submit_parses_ack():
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 7, "created": False, "contributor": "Plant 01",
                "metric_code": "specific_thermal_energy", "period_label": "2026-07",
                "value": "3255.000000",
            },
        )
    )
    with HubClient(CONFIG) as client:
        ack = client.submit(PAYLOAD)
    assert ack.id == 7
    assert ack.created is False


@respx.mock
def test_401_is_not_retryable_and_mentions_the_token():
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token."})
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError) as exc:
        client.submit(PAYLOAD)
    assert exc.value.retryable is False
    assert "BUSSOLA_TOKEN" in str(exc.value)


@respx.mock
def test_409_is_retryable():
    """The period is not open yet — a later run will succeed."""
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(409, json={"detail": "Period is closed."})
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError) as exc:
        client.submit(PAYLOAD)
    assert exc.value.retryable is True


@respx.mock
def test_422_is_not_retryable():
    """The data is wrong — retrying it unchanged never helps."""
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(422, json={"detail": "Value out of bounds."})
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError) as exc:
        client.submit(PAYLOAD)
    assert exc.value.retryable is False


@respx.mock
def test_500_is_retryable():
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(503, text="upstream down")
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError) as exc:
        client.submit(PAYLOAD)
    assert exc.value.retryable is True


@respx.mock
def test_network_failure_is_retryable():
    respx.post("https://hub.example/api/v1/submissions/").mock(
        side_effect=httpx.ConnectError("no route to host")
    )
    with HubClient(CONFIG) as client, pytest.raises(HubError) as exc:
        client.submit(PAYLOAD)
    assert exc.value.retryable is True
