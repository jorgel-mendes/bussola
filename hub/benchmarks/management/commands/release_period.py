"""Publish differentially private benchmarks for a period.

Releasing is an explicit operator action, never a side effect of somebody
looking at a page. That separation is the whole reason this command exists:
if rendering the dashboard released statistics, a browser refresh would spend
privacy budget, and a crawler would exhaust a collaboration's entire annual
allowance in a few seconds. Viewing reads what was already published.

    python hub/manage.py release_period --collaboration bahia-industry \\
        --period 2026-07 --epsilon 1.0

Epsilon is PER CELL -- per (cohort, metric) -- and is split evenly across the
statistics in that metric's catalog entry. Releasing a period with 2 cohorts
and 2 metrics at --epsilon 1.0 therefore charges up to 4.0 against the period's
budget, and the command says so before it starts.

Already-released cells are skipped rather than re-released: a cell is published
once (REVIEW section F1), because re-running a mechanism on the same data
spends budget again and yields a second sample of the same private quantity.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from benchmarks.models import BenchmarkRelease
from benchmarks.releases import release_benchmark, statistics_to_release
from budget.accountant import budget_for
from budget.exceptions import BudgetError, BudgetExhausted
from collaborations.models import Collaboration
from ingest.models import ReportingPeriod


class Command(BaseCommand):
    help = "Publish DP benchmarks for every cell in a reporting period."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--collaboration", required=True, help="Collaboration slug.")
        parser.add_argument("--period", required=True, help="Period label, e.g. 2026-07.")
        parser.add_argument(
            "--epsilon",
            required=True,
            type=Decimal,
            help="Epsilon per cell, split evenly across that metric's statistics.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be released and what it would cost. Spends nothing.",
        )

    def handle(self, *args, **options) -> None:
        collaboration = self._get_collaboration(options["collaboration"])
        period = self._get_period(collaboration, options["period"])
        epsilon = options["epsilon"]

        if epsilon <= 0:
            raise CommandError("--epsilon must be positive.")

        budget = budget_for(period)
        cells = [
            (cohort, metric)
            for cohort in collaboration.cohorts.all()
            for metric in collaboration.metrics.filter(is_active=True)
        ]
        # One query for every already-published cell, rather than an exists()
        # per cell. At demo scale that is 6 queries against 1, so this is a
        # code-quality fix and not a live performance problem -- but the loop
        # scales with cohorts x metrics, and a collaboration with 20 cohorts and
        # 10 metrics would issue 200 round trips to learn something one query
        # answers.
        published_pairs = set(
            BenchmarkRelease.objects.filter(period=period).values_list(
                "cohort_id", "metric_id"
            )
        )
        pending = [
            (cohort, metric)
            for cohort, metric in cells
            if (cohort.pk, metric.pk) not in published_pairs
        ]

        self.stdout.write(f"Collaboration : {collaboration.name}")
        self.stdout.write(f"Period        : {period.label}")
        self.stdout.write(
            f"Budget        : {budget.epsilon_total} total, "
            f"{budget.remaining()} remaining"
        )
        self.stdout.write(
            f"Cells         : {len(pending)} to release "
            f"({len(cells) - len(pending)} already published)"
        )
        self.stdout.write(f"Maximum cost  : {epsilon * len(pending)}")

        if not pending:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if options["dry_run"]:
            for cohort, metric in pending:
                releasable, skipped = statistics_to_release(metric)
                self.stdout.write(
                    f"  would release {cohort.code}/{metric.code}: "
                    f"{', '.join(releasable) or 'nothing'}"
                    + (f" (skipping {', '.join(skipped)})" if skipped else "")
                )
            self.stdout.write(self.style.WARNING("Dry run — no budget spent."))
            return

        published = suppressed = 0
        for cohort, metric in pending:
            try:
                # Each cell is its own transaction. A cell that cannot be paid
                # for must not undo cells that were already published and
                # charged -- those are real disclosures and the ledger has to
                # keep them.
                with transaction.atomic():
                    outcome = release_benchmark(
                        cohort=cohort, metric=metric, period=period, epsilon=epsilon
                    )
            except BudgetExhausted as exc:
                # exc.remaining was measured INSIDE the transaction that then
                # rolled back, after some of this cell's statistics had already
                # been charged. Reporting it as "remaining" tells the operator
                # they have less budget than they actually do -- the rollback
                # gave those charges back. Re-read after the rollback instead.
                self.stdout.write(
                    self.style.ERROR(
                        f"  REFUSED {cohort.code}/{metric.code}: this cell needs "
                        f"{exc.requested} per statistic and the budget cannot cover "
                        f"the whole cell. Nothing was published for it. "
                        f"Actually remaining after rollback: {budget.remaining()}. "
                        f"Stopping."
                    )
                )
                break
            except BudgetError as exc:
                raise CommandError(f"{cohort.code}/{metric.code}: {exc}") from exc

            if outcome.suppressed:
                suppressed += 1
                self.stdout.write(
                    f"  suppressed {cohort.code}/{metric.code}: "
                    f"{outcome.n_contributors} of {outcome.min_contributors} required"
                )
                continue

            published += 1
            values = ", ".join(
                f"{s.statistic}={s.value:.1f}" for s in outcome.statistics
            )
            self.stdout.write(
                f"  released   {cohort.code}/{metric.code}: {values} "
                f"(n={outcome.n_contributors}, ε={outcome.release.epsilon_spent})"
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{published} released, {suppressed} suppressed. "
                f"Budget remaining: {budget.remaining()}"
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
