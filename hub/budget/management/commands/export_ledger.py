"""Export a period's epsilon ledger as CSV (S3-4).

For the Auditor who wants the record outside the admin -- in a spreadsheet, a
notebook, or an evidence pack for a compliance file.

It RECONCILES before it hands anything over. The row count written is checked
against the ledger's own count, and the cumulative total against
`BudgetPeriod.spent()`. An export that quietly dropped rows would give an
auditor an incomplete record that still looks complete, and they would sign it
off -- which is a worse failure than the command refusing to run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from budget.export import export_filename, write_ledger_csv
from budget.models import BudgetPeriod
from collaborations.models import Collaboration
from ingest.models import ReportingPeriod


class Command(BaseCommand):
    help = "Export a reporting period's epsilon ledger as CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--collaboration", required=True, help="Collaboration slug.")
        parser.add_argument("--period", required=True, help="Period label, e.g. 2026-07.")
        parser.add_argument(
            "--out",
            type=Path,
            default=None,
            help="Output file. Defaults to a named file in the working directory; "
            "pass '-' to write to stdout.",
        )

    def handle(self, *args, **options) -> None:
        collaboration = self._get_collaboration(options["collaboration"])
        period = self._get_period(collaboration, options["period"])

        try:
            budget = period.budget
        except BudgetPeriod.DoesNotExist as exc:
            raise CommandError(
                f"Period {period.label!r} has no budget, so it has no ledger to export. "
                f"Nothing has been released against it."
            ) from exc

        entries = budget.entries.select_related(
            "budget_period__period__collaboration", "cohort", "metric"
        ).order_by("created_at", "id")
        expected = entries.count()

        if options["out"] is not None and str(options["out"]) == "-":
            written = write_ledger_csv(entries, sys.stdout, budget_total=budget.epsilon_total)
            destination = "stdout"
        else:
            path = options["out"] or Path(
                export_filename(
                    collaboration_slug=collaboration.slug, period_label=period.label
                )
            )
            with path.open("w", newline="", encoding="utf-8") as fh:
                written = write_ledger_csv(entries, fh, budget_total=budget.epsilon_total)
            destination = str(path)

        # Reconciliation. See the module docstring: a short export that looks
        # complete is the failure this guards.
        if written != expected:
            raise CommandError(
                f"Export is incomplete: wrote {written} rows for a ledger of "
                f"{expected}. The file at {destination} must not be treated as an "
                f"audit record."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{written} ledger entries written to {destination}.\n"
                f"Reconciles: spent ε={budget.spent()} of ε={budget.epsilon_total}, "
                f"remaining ε={budget.remaining()}."
            )
        )

    # --- lookups -----------------------------------------------------------

    def _get_collaboration(self, slug: str) -> Collaboration:
        try:
            return Collaboration.objects.get(slug=slug, is_active=True)
        except Collaboration.DoesNotExist as exc:
            raise CommandError(f"No active collaboration with slug {slug!r}.") from exc

    def _get_period(self, collaboration: Collaboration, label: str) -> ReportingPeriod:
        try:
            return ReportingPeriod.objects.get(collaboration=collaboration, label=label)
        except ReportingPeriod.DoesNotExist as exc:
            raise CommandError(
                f"Collaboration {collaboration.slug!r} has no period {label!r}."
            ) from exc
