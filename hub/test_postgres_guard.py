"""Fail the build when tests that must run were skipped instead.

A skipped test is green. That is the whole problem.

The concurrency tests (`budget/test_concurrency.py`) skip on SQLite, because
`select_for_update()` is a no-op there and they would otherwise pass while
proving nothing. Skipping is the right behaviour locally. In CI it is a
disaster waiting to happen: a mistyped DATABASE_URL, a Postgres service that
failed to come up, or a settings change would silently turn the project's most
important test into four skips and a green tick, and nobody would look again.

So CI sets BUSSOLA_REQUIRE_POSTGRES=1 and this module turns that silence into
a failure.

This is retro action A3 -- "treat 'looks fine' as unverified" -- expressed as
code rather than as a good intention. It is the same class of control as
`test_naming_drift.py`: a guard that fails the build rather than a convention
that relies on someone remembering.
"""

from __future__ import annotations

import os

import pytest
from django.db import connection

from config.settings.test import using_postgres

REQUIRED = os.environ.get("BUSSOLA_REQUIRE_POSTGRES", "").strip() in {"1", "true", "True"}


@pytest.mark.skipif(not REQUIRED, reason="BUSSOLA_REQUIRE_POSTGRES not set (local run)")
@pytest.mark.django_db
def test_this_environment_is_actually_running_postgres():
    """BUSSOLA_REQUIRE_POSTGRES=1 promises a real transactional database."""
    assert using_postgres(), (
        "BUSSOLA_REQUIRE_POSTGRES=1 but the tests are running on "
        f"{connection.vendor}. The concurrency tests would skip, the build "
        "would still be green, and the privacy guarantee would be unverified."
    )


@pytest.mark.skipif(not REQUIRED, reason="BUSSOLA_REQUIRE_POSTGRES not set (local run)")
@pytest.mark.django_db
def test_row_level_locking_is_available():
    """The specific capability the accountant's correctness rests on.

    Asserted directly rather than inferred from the backend name, because it is
    the feature -- not the vendor string -- that makes the critical section a
    critical section.
    """
    assert connection.features.has_select_for_update, (
        "This backend cannot SELECT ... FOR UPDATE. budget.accountant.spend() "
        "has no critical section here and concurrent releases can double-spend."
    )
