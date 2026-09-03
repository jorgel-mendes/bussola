"""bootstrap_deploy tests.

This command runs unattended at container start on a platform with no shell, so
its exit-code contract is the whole point (retro action A3): a clean exit must
mean "the hub is in the state the operator expects", never "nothing happened
and nothing complained".
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from collaborations.models import Collaboration

pytestmark = pytest.mark.django_db

User = get_user_model()


def run(**env):
    """Run the command with a controlled environment."""
    import os
    from io import StringIO

    keys = [
        "DJANGO_SUPERUSER_USERNAME",
        "DJANGO_SUPERUSER_PASSWORD",
        "DJANGO_SUPERUSER_EMAIL",
        "BUSSOLA_SEED_DEMO",
    ]
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env)
    out = StringIO()
    try:
        call_command("bootstrap_deploy", stdout=out)
    finally:
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in saved.items() if v is not None})
    return out.getvalue()


# --- not configured: boot anyway -----------------------------------------


def test_an_unconfigured_bootstrap_does_nothing_and_succeeds():
    """The service must boot whether or not anyone asked for a demo user."""
    output = run()

    assert User.objects.count() == 0
    assert Collaboration.objects.count() == 0
    assert "no admin user created" in output
    assert "no demo data seeded" in output


def test_a_username_without_a_password_creates_nothing():
    """Half-configured is not configured. Creating a passwordless superuser on
    a public deployment would be worse than creating none."""
    run(DJANGO_SUPERUSER_USERNAME="analyst")

    assert User.objects.count() == 0


# --- configured: do it ----------------------------------------------------


def test_a_configured_bootstrap_creates_the_superuser():
    run(
        DJANGO_SUPERUSER_USERNAME="analyst",
        DJANGO_SUPERUSER_PASSWORD="s3cret-not-real",
        DJANGO_SUPERUSER_EMAIL="analyst@example.org",
    )

    user = User.objects.get(username="analyst")
    assert user.is_superuser and user.is_staff
    assert user.email == "analyst@example.org"
    assert user.check_password("s3cret-not-real")


def test_running_twice_is_idempotent():
    """Containers restart. A bootstrap that failed on the second boot would
    make every restart a deploy failure."""
    run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="first-password")
    output = run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="second-password")

    assert User.objects.count() == 1
    assert "already exists" in output


def test_it_does_not_rewrite_an_existing_admin_password():
    """A deploy that silently reset the admin password on every restart would be
    a credential-rotation mechanism nobody asked for -- and it would lock out an
    operator who had deliberately changed it."""
    run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="first-password")
    run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="second-password")

    assert User.objects.get(username="analyst").check_password("first-password")


def test_seeding_is_opt_in_and_creates_the_demo_collaboration():
    run(BUSSOLA_SEED_DEMO="1")

    assert Collaboration.objects.filter(slug="bahia-industry").exists()


def test_a_failed_seed_fails_the_deploy_rather_than_booting_empty():
    """If seeding was asked for and cannot be done, the container must not come
    up looking ready. Swallowing the error is how a hub gets deployed empty
    while the dashboard reports success."""
    from unittest.mock import patch

    with patch(
        "collaborations.management.commands.bootstrap_deploy.call_command",
        side_effect=RuntimeError("seed blew up"),
    ), pytest.raises(RuntimeError, match="seed blew up"):
        run(BUSSOLA_SEED_DEMO="1")


# --- tokens must not reach the deploy log ---------------------------------


def test_bootstrap_seeding_never_emits_raw_tokens():
    """stdout at container boot is a retained deploy log.

    DESIGN.md section 3.4 stores only token hashes so that a database dump
    yields no usable credential. Printing the raw keys into a log that anyone
    with dashboard access can read would undo that entirely.
    """
    from contributors.models import ApiToken

    output = run(BUSSOLA_SEED_DEMO="1")

    assert ApiToken.objects.exists(), "tokens should still be issued"
    assert "NOT emitted" in output
    # No 43-character url-safe base64 token anywhere in the output.
    import re

    assert not re.search(r"[A-Za-z0-9_-]{40,}", output), output


# --- the admin this provisions is on the public internet ------------------


def test_a_weak_password_fails_the_deploy_rather_than_provisioning_a_public_admin():
    """create_superuser() does not run AUTH_PASSWORD_VALIDATORS.

    Without this check a deploy can stand up an internet-reachable admin with a
    guessable credential and report success -- on the console that governs a
    privacy system.
    """
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="rejected"):
        run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="analyst")

    assert User.objects.count() == 0


def test_a_password_matching_the_username_is_rejected():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="too similar"):
        run(DJANGO_SUPERUSER_USERNAME="admin", DJANGO_SUPERUSER_PASSWORD="admin")


def test_a_common_password_is_rejected():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="too common"):
        run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="password")


def test_a_short_password_is_rejected():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="rejected"):
        run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="ab3")


def test_a_strong_password_is_accepted():
    run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="tR7-quartile-ledger-92")

    assert User.objects.get(username="analyst").is_superuser


def test_a_restart_with_a_weak_env_password_does_not_fail_the_deploy():
    """Found in review of PR #1: validation ran before the existence check.

    This command never resets an existing admin's password, so on a restart the
    environment value is inert. Failing the boot over an inert value would break
    exactly the idempotency the command exists to provide -- every container
    restart would become a deploy failure.
    """
    run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="tR7-quartile-ledger-92")

    output = run(DJANGO_SUPERUSER_USERNAME="analyst", DJANGO_SUPERUSER_PASSWORD="admin")

    assert "already exists" in output
    assert User.objects.count() == 1
    assert User.objects.get(username="analyst").check_password("tR7-quartile-ledger-92")
