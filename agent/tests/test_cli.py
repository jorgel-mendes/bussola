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


# --- position (S3-1) --------------------------------------------------------

POSITION_JSON = {
    "contract_version": "1.0",
    "metric_code": "specific_thermal_energy",
    "metric_unit": "MJ/t clinker",
    "period_label": "2026-07",
    "cohort_code": "2320",
    "your_value": "3100.000000",
    "n_contributors": 47,
    "epsilon_spent": "1.000000",
    "released_q25": "3000.000000",
    "released_median": "3400.000000",
    "released_q75": "3800.000000",
    "quartile": "Q2",
    "is_usable": True,
    "caveat": "Quartile boundaries are differentially private releases.",
}


@respx.mock
def test_position_reports_the_quartile(env):
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(200, json=POSITION_JSON)
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert result.exit_code == 0
    assert "You are in Q2." in result.stdout
    assert "47 contributors" in result.stdout


@respx.mock
def test_position_shows_the_caveat_that_the_boundaries_are_noisy(env):
    """A quartile shown without it would be read as an exact placement."""
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(200, json=POSITION_JSON)
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert "differentially private" in result.stdout


@respx.mock
def test_position_refuses_to_place_the_plant_on_an_unusable_release(env):
    """The Sprint 2 N=6 finding, as the member experiences it."""
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(
            200,
            json={
                **POSITION_JSON,
                "released_q25": "3800.000000",
                "released_q75": "3000.000000",
                "quartile": "unknown",
                "is_usable": False,
                "caveat": "This release is too noisy to place you against.",
            },
        )
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert result.exit_code == 0
    assert "cannot be reported" in result.stdout
    assert "too noisy" in result.stdout
    # The numbers are still shown, so the operator can see WHY it was refused.
    assert "3800.000000" in result.stdout


@respx.mock
def test_position_not_yet_released_is_retryable_not_a_failure(env):
    """For most of a reporting period this is simply the state of the world.

    Exit 3, not 1 or 2: nothing at the plant needs to change, and the same call
    will succeed once the operator releases. A red error here would train an
    operator to ignore the agent's log.
    """
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(
            404, json={"detail": "Nothing has been published yet.", "code": "not_published"}
        )
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert result.exit_code == EXIT_RETRYABLE


@respx.mock
def test_position_without_a_submission_is_a_local_problem(env):
    """Retrying never fixes this one — the plant has to submit first."""
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(
            404, json={"detail": "You have not submitted.", "code": "not_submitted"}
        )
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert result.exit_code == EXIT_LOCAL_ERROR


@respx.mock
def test_position_reports_a_revoked_token_as_rejected(env):
    respx.get("https://hub.example/api/v1/position/").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token."})
    )

    result = runner.invoke(app, ["position", "--metric", "specific_thermal_energy",
                                 "--period", "2026-07"])

    assert result.exit_code == EXIT_REJECTED
