"""Bring a freshly deployed hub to a usable state, idempotently.

Render's free tier has no shell, so there is no way to run `createsuperuser` or
`seed_demo` by hand after a deploy. Without them the deployed hub is an empty
database behind a login nobody can pass -- and the admin *is* the Analyst and
Auditor console (SPEC section 2), so that is most of the product.

Deliberately a management command rather than a longer `&&` chain in the
Dockerfile CMD. Sprint 1's third defect was a shell command that grew inside a
config file until YAML silently split it, while the exit status still looked
clean. Startup logic belongs somewhere it can be read, tested and exit properly.

The exit-code contract matters more than usual here, because this runs
unattended at container start (retro action A3):

  * Not configured        -> skip, say so, exit 0. The service must boot
                             whether or not anyone asked for a demo user.
  * Configured, succeeded -> do it, say so, exit 0.
  * Configured, failed    -> raise. A deploy that was asked to create an admin
                             and could not must fail loudly, not boot into a
                             state the operator believes is ready.

Environment:

    DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD
        Create this superuser if it does not already exist. Standard Django
        variable names, so `createsuperuser --noinput` uses them too.

    BUSSOLA_SEED_DEMO=1
        Also run `seed_demo`, which is itself idempotent.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Idempotently create the demo superuser and seed demo data, if configured."

    def handle(self, *args, **options) -> None:
        self._ensure_superuser()
        self._maybe_seed()

    # --- superuser ---------------------------------------------------------

    def _ensure_superuser(self) -> None:
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()

        if not username or not password:
            self.stdout.write(
                "bootstrap: DJANGO_SUPERUSER_USERNAME/_PASSWORD not set — "
                "no admin user created."
            )
            return

        User = get_user_model()

        # Existence check FIRST. This command deliberately does not reset an
        # existing admin's password, so on a restart the environment value is
        # inert -- and failing the boot over an inert value would break the
        # idempotency the command exists to provide. Found in review of PR #1.
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"bootstrap: superuser '{username}' already exists — unchanged.")
            return

        # create_superuser() does NOT run AUTH_PASSWORD_VALIDATORS -- they only
        # fire in forms and in the interactive createsuperuser. So a deploy can
        # otherwise provision a public admin with "admin"/"admin" and report
        # success. This is the console that governs a privacy system; it is
        # reachable from the internet the moment the service is up.
        #
        # Refusing is deliberate. A deploy that was told to create an admin and
        # was handed an unusable credential must fail loudly rather than boot
        # into a state the operator believes is secure.
        try:
            validate_password(password, User(username=username, email=email or ""))
        except ValidationError as exc:
            raise CommandError(
                "bootstrap: DJANGO_SUPERUSER_PASSWORD was rejected — "
                + " ".join(exc.messages)
                + " This admin is publicly reachable; set a strong password in the "
                "hosting dashboard and redeploy."
            ) from exc

        User.objects.create_superuser(username=username, email=email or "", password=password)
        self.stdout.write(self.style.SUCCESS(f"bootstrap: created superuser '{username}'."))

    # --- demo data ---------------------------------------------------------

    def _maybe_seed(self) -> None:
        if os.environ.get("BUSSOLA_SEED_DEMO", "").strip() not in {"1", "true", "True"}:
            self.stdout.write("bootstrap: BUSSOLA_SEED_DEMO not set — no demo data seeded.")
            return

        self.stdout.write("bootstrap: seeding demo collaboration…")
        # No try/except: if seeding was asked for and fails, the deploy must
        # fail. Swallowing it would leave a hub that looks deployed and is empty.
        #
        # --no-token-output is not optional here. stdout at container boot is a
        # retained deploy log, and DESIGN.md section 3.4 stores only token
        # hashes precisely so that a dump yields no usable credential. Printing
        # the raw keys into a log would undo that in the one product whose
        # premise is not leaking things.
        call_command("seed_demo", no_token_output=True, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("bootstrap: demo data seeded."))
