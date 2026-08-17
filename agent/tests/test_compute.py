"""Local computation tests.

Everything here runs on the plant's machine. The failure messages matter as much
as the failures: an operator reading them at 3am is the intended audience.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from bussola_agent.compute import ComputationError, check_bounds, load_records, local_mean
from bussola_contracts import MetricSpec

SPEC = MetricSpec(
    code="specific_thermal_energy",
    name="Specific thermal energy",
    unit="MJ/t clinker",
    value_type="continuous",
    lower_bound=Decimal("1760"),
    upper_bound=Decimal("7100"),
    bounds_rationale="Thermodynamic floor (reaction enthalpy) and wet-kiln ceiling.",
    contributions_per_period=1,
    statistics=["median"],
)


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "energy.csv"
    path.write_text(
        "period,day,value\n"
        "2026-07,1,3400.0\n"
        "2026-07,2,3410.0\n"
        "2026-07,3,3420.0\n"
        "2026-08,1,7000.0\n",
        encoding="utf-8",
    )
    return path


def test_loads_all_records_when_no_period_given(csv_file):
    assert load_records(csv_file, "value").len() == 4


def test_filters_to_the_requested_period(csv_file):
    """Submitting a value computed over the wrong window is silently wrong —
    the number looks plausible and nothing errors — so this is filtered hard."""
    series = load_records(csv_file, "value", period="2026-07")
    assert series.len() == 3
    assert series.max() == 3420.0


def test_missing_period_is_a_hard_failure(csv_file):
    with pytest.raises(ComputationError, match="No records for period"):
        load_records(csv_file, "value", period="2030-01")


def test_missing_file_names_the_path(tmp_path):
    with pytest.raises(ComputationError, match="Data file not found"):
        load_records(tmp_path / "nope.csv", "value")


def test_missing_column_lists_available_columns(csv_file):
    with pytest.raises(ComputationError, match="Available: period, day, value"):
        load_records(csv_file, "kwh")


def test_all_null_column_is_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("period,value\n2026-07,\n2026-07,\n", encoding="utf-8")
    with pytest.raises(ComputationError, match="no non-null values"):
        load_records(path, "value", period="2026-07")


def test_local_mean(csv_file):
    series = load_records(csv_file, "value", period="2026-07")
    assert local_mean(series) == Decimal("3410")


def test_check_bounds_passes_inside_range():
    check_bounds(Decimal("3410"), SPEC)  # must not raise


@pytest.mark.parametrize("value", ["500", "50000"])
def test_check_bounds_rejects_outside_range(value):
    with pytest.raises(ComputationError) as exc:
        check_bounds(Decimal(value), SPEC)
    message = str(exc.value)
    # The operator needs the rationale and the reassurance, not just a number.
    assert "Thermodynamic floor" in message
    assert "Nothing has been submitted" in message


def test_check_bounds_is_inclusive():
    check_bounds(Decimal("1760"), SPEC)
    check_bounds(Decimal("7100"), SPEC)


def test_mean_of_single_record(tmp_path):
    path = tmp_path / "one.csv"
    path.write_text("period,value\n2026-07,3412.5\n", encoding="utf-8")
    series = load_records(path, "value", period="2026-07")
    assert local_mean(series) == Decimal("3412.5")


def test_polars_series_length_is_the_record_count(csv_file):
    """n_records is submitted to the hub and, from Sprint 2, feeds the privacy
    unit; it must be the true count of underlying records."""
    series = load_records(csv_file, "value", period="2026-07")
    assert series.len() == 3
    assert isinstance(series, pl.Series)
