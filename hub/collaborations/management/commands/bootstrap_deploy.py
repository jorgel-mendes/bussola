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

    BUSSOLA_DEMO_PERIOD=2026-07
        Populate that period with submissions, so the deployed hub has
        something to publish. Without this the hub is a correct but empty
        system: contributors registered, no data, every cell suppressed at
        0 < min_contributors. A reviewer opening the URL cold sees nothing.

    BUSSOLA_DEMO_RESERVE="plant-01 plant-02 plant-03"
        Contributors to leave OUT of that bulk load, reserved for the agent
        containers to submit live. The multi-party claim belongs to the real
        agents crossing a real network boundary; this only fills the cohort
        up to a size where a DP quantile means anything.

    BUSSOLA_DEMO_BUDGET=6.0     epsilon_total for the period, if not already set
    BUSSOLA_DEMO_EPSILON=1.0    epsilon per cell; runs release_period
"""

from __future__ import annotations

import os
from pathlib import Path

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
        self._maybe_populate()

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

    # --- demo data and releases --------------------------------------------

    def _maybe_populate(self) -> None:
        """Give the deployed hub something to publish.

        Deliberately guarded on "are there already submissions for this
        period?" rather than on a flag alone. Regenerating and reloading on
        every container restart would be wasted work, and re-running
        release_period against a period whose budget is already spent would
        print refusals into the boot log on every deploy.
        """
        label = os.environ.get("BUSSOLA_DEMO_PERIOD", "").strip()
        if not label:
            self.stdout.write("bootstrap: BUSSOLA_DEMO_PERIOD not set — no demo data loaded.")
            return

        from django.conf import settings

        from ingest.models import ReportingPeriod, Submission

        try:
            period = ReportingPeriod.objects.get(label=label)
        except ReportingPeriod.DoesNotExist:
            raise CommandError(
                f"bootstrap: BUSSOLA_DEMO_PERIOD={label!r} does not exist. "
                f"Seed the collaboration first (BUSSOLA_SEED_DEMO=1)."
            ) from None
        except ReportingPeriod.MultipleObjectsReturned:
            raise CommandError(
                f"bootstrap: more than one collaboration has a period {label!r}. "
                f"Load its submissions by hand rather than guessing which."
            ) from None

        if Submission.objects.filter(period=period).exists():
            self.stdout.write(
                f"bootstrap: {label} already has submissions — nothing reloaded."
            )
        else:
            self._generate_and_load(period, settings)

        self._maybe_release(period)

    def _generate_and_load(self, period, settings) -> None:
        """Generate synthetic data and load it as submissions.

        The data is generated rather than shipped: `data/` is gitignored
        because it holds issued tokens, and `datagen` is deterministic under
        its fixed seed, so generating at boot gives byte-identical values to a
        committed copy without committing 3 MB of CSV or any credential.
        """
        import subprocess
        import sys
        import tempfile

        generator = settings.REPO_DIR / "datagen" / "generate.py"
        if not generator.exists():
            raise CommandError(f"bootstrap: {generator} is missing from this image.")

        reserved = os.environ.get("BUSSOLA_DEMO_RESERVE", "").split()
        collaboration = period.collaboration

        with tempfile.TemporaryDirectory() as tmp:
            self.stdout.write("bootstrap: generating synthetic contributor data…")
            result = subprocess.run(
                [
                    sys.executable,
                    str(generator),
                    "--contributors",
                    str(collaboration.contributors.count()),
                    "--periods",
                    str(collaboration.periods.count()),
                    "--out",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            # Checked explicitly rather than through a pipe. Sprint 1's third
            # defect was a command whose exit status still looked clean.
            if result.returncode != 0:
                raise CommandError(
                    f"bootstrap: datagen failed ({result.returncode}): {result.stderr[-500:]}"
                )

            call_command(
                "load_submissions",
                collaboration=collaboration.slug,
                data_dir=Path(tmp),
                period=period.label,
                skip=reserved,
                stdout=self.stdout,
            )
        if reserved:
            self.stdout.write(
                f"bootstrap: reserved {', '.join(reserved)} for live agent submissions."
            )

    def _maybe_release(self, period) -> None:
        from decimal import Decimal

        from budget.models import BudgetPeriod

        total = os.environ.get("BUSSOLA_DEMO_BUDGET", "").strip()
        epsilon = os.environ.get("BUSSOLA_DEMO_EPSILON", "").strip()

        if total:
            budget, created = BudgetPeriod.objects.get_or_create(
                period=period, defaults={"epsilon_total": Decimal(total)}
            )
            # get_or_create, never update. Raising a budget that already has
            # spends against it would retroactively authorise disclosure the
            # collaboration never agreed to, and doing it silently on every
            # container restart would be worse still.
            if created:
                self.stdout.write(f"bootstrap: budget for {period.label} set to ε={total}.")
            else:
                self.stdout.write(
                    f"bootstrap: {period.label} already has a budget "
                    f"(ε={budget.epsilon_total}, {budget.remaining()} remaining) — unchanged."
                )

        if not epsilon:
            self.stdout.write("bootstrap: BUSSOLA_DEMO_EPSILON not set — nothing released.")
            return

        call_command(
            "release_period",
            collaboration=period.collaboration.slug,
            period=period.label,
            epsilon=Decimal(epsilon),
            stdout=self.stdout,
        )
