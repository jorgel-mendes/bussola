"""Fixtures for the sweep.

The grid is parameterised into 35 independent test items, but it produces ONE
artifact. `sweep_writer` is what joins them: each cell appends its trials, and
the CSV is written once when the session ends.

Session-scoped and append-only on purpose. A per-test writer would leave 35
files to stitch together by hand, and stitching by hand is where a cell goes
missing without anyone noticing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation import sweep

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results" / "sweep.csv"


def pytest_addoption(parser):
    parser.addoption(
        "--sweep-out",
        action="store",
        default=str(DEFAULT_OUTPUT),
        help="Where the sweep CSV is written.",
    )


@pytest.fixture(scope="session")
def _sweep_results():
    return []


@pytest.fixture(scope="session")
def sweep_writer(request, _sweep_results):
    """Collect each cell's trials; write the CSV once at the end of the session."""

    def append(results):
        _sweep_results.extend(results)

    yield append

    if _sweep_results:
        path = sweep.write_csv(_sweep_results, Path(request.config.getoption("--sweep-out")))
        print(f"\nSweep: {len(_sweep_results)} trials written to {path}")
