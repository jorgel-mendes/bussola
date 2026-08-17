"""CLI tests.

Exit codes are the agent's real interface when it runs from cron, so they are
asserted explicitly rather than treated as incidental.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bussola_agent.cli import EXIT_LOCAL_ERROR, EXIT_REJECTED, EXIT_RETRYABLE, app

runner = CliRunner()

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


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BUSSOLA_HUB_URL", "https://hub.example")
    monkeypatch.setenv("BUSSOLA_TOKEN", "tok")
    monkeypatch.setenv("BUSSOLA_CONTRIBUTOR_LABEL", "plant-01")


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "energy.csv"
    path.write_text(
        "period,day,value\n2026-07,1,3400.0\n2026-07,2,3410.0\n2026-07,3,3420.0\n",
        encoding="utf-8",
    )
    return path


def args(data_file, *extra):
    return [
        "submit",
        "--metric", "specific_thermal_energy",
        "--period", "2026-07",
        "--file", str(data_file),
        *extra,
    ]


def test_missing_config_exits_with_local_error(tmp_path, monkeypatch, data_file):
    monkeypatch.delenv("BUSSOLA_HUB_URL", raising=False)
    monkeypatch.delenv("BUSSOLA_TOKEN", raising=False)
    result = runner.invoke(app, args(data_file))
    assert result.exit_code == EXIT_LOCAL_ERROR
    assert "BUSSOLA_HUB_URL" in result.output


@respx.mock
def test_dry_run_sends_nothing(env, data_file):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    submit_route = respx.post("https://hub.example/api/v1/submissions/")

    result = runner.invoke(app, args(data_file, "--dry-run"))

    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "3410" in result.output
    assert not submit_route.called, "dry run must not contact the submissions endpoint"


@respx.mock
def test_successful_submit(env, data_file):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 1, "created": True, "contributor": "Plant 01",
                "metric_code": "specific_thermal_energy", "period_label": "2026-07",
                "value": "3410.000000",
            },
        )
    )
    result = runner.invoke(app, args(data_file))
    assert result.exit_code == 0
    assert "Submitted" in result.output


@respx.mock
def test_resubmission_is_reported_as_an_update(env, data_file):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1, "created": False, "contributor": "Plant 01",
                "metric_code": "specific_thermal_energy", "period_label": "2026-07",
                "value": "3410.000000",
            },
        )
    )
    result = runner.invoke(app, args(data_file))
    assert result.exit_code == 0
    assert "Updated existing submission" in result.output


@respx.mock
def test_out_of_bounds_value_fails_locally_without_calling_the_hub(env, tmp_path):
    """The bounds check runs on the plant machine, so a unit error is caught
    before anything leaves the building."""
    path = tmp_path / "bad.csv"
    path.write_text("period,value\n2026-07,41000.0\n", encoding="utf-8")

    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    submit_route = respx.post("https://hub.example/api/v1/submissions/")

    result = runner.invoke(app, args(path))

    assert result.exit_code == EXIT_LOCAL_ERROR
    assert not submit_route.called
    assert "Thermodynamic floor" in result.output


@respx.mock
def test_closed_period_exits_retryable(env, data_file):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(409, json={"detail": "Period is closed."})
    )
    result = runner.invoke(app, args(data_file))
    assert result.exit_code == EXIT_RETRYABLE


@respx.mock
def test_rejected_value_exits_non_retryable(env, data_file):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    respx.post("https://hub.example/api/v1/submissions/").mock(
        return_value=httpx.Response(422, json={"detail": "Out of bounds."})
    )
    result = runner.invoke(app, args(data_file))
    assert result.exit_code == EXIT_REJECTED


def test_missing_data_file_exits_local_error(env, tmp_path):
    with respx.mock:
        respx.get("https://hub.example/api/v1/metrics/").mock(
            return_value=httpx.Response(200, json=METRIC_JSON)
        )
        result = runner.invoke(app, args(tmp_path / "absent.csv"))
    assert result.exit_code == EXIT_LOCAL_ERROR


@respx.mock
def test_check_command_reports_reachability(env):
    respx.get("https://hub.example/api/v1/metrics/").mock(
        return_value=httpx.Response(200, json=METRIC_JSON)
    )
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "hub reachable" in result.output
    assert "specific_thermal_energy" in result.output
