"""Load contributor aggregates from datagen output, without the agent.

Why this exists, stated plainly so the demo does not overclaim:

The multi-party path -- an agent computing an aggregate on its own machine and
submitting it over the network -- is proven by the docker-compose demo, with
separate containers, volumes and tokens. That is the real claim and it is
demonstrated with real containers.

It does not scale to a demo audience. The privacy-utility floor measured in the
OpenDP spike (ADR-0003) means a DP quantile needs roughly 50 contributors to be
worth publishing, and running 50 agent containers to show one benchmark is
theatre with a longer runtime. This command loads the remaining contributors'
aggregates directly, computing exactly what the agent would have computed from
the same CSV -- the mean of that period's daily records.

So: a few contributors submit through the real network path, the rest are
loaded here, and the demo says which is which. The alternative -- shrinking the
demo until the agent count is plausible -- would put the benchmark back below
the utility floor and make every published number meaningless.

    python hub/manage.py load_submissions --collaboration bahia-industry \\
        --data-dir data --period 2026-07 --skip plant-01 plant-02 plant-03
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from collaborations.models import Collaboration
from ingest.models import Submission

AGENT_VERSION = "load_submissions"


class Command(BaseCommand):
    help = "Load per-contributor aggregates from datagen CSVs into submissions."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--collaboration", required=True)
        parser.add_argument("--data-dir", type=Path, default=Path("data"))
        parser.add_argument(
            "--period",
            help="Period label. Omit to load every period present in the data.",
        )
        parser.add_argument(
            "--skip",
            nargs="*",
            default=[],
            help=(
                "Contributor slugs to leave out — use for the contributors that "
                "submit through the real agent, so the demo does not double up."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        collaboration = self._get_collaboration(options["collaboration"])
        data_dir: Path = options["data_dir"]
        if not data_dir.is_dir():
            raise CommandError(f"{data_dir} is not a directory. Run datagen first.")

        metrics = {m.code: m for m in collaboration.metrics.filter(is_active=True)}
        periods = {p.label: p for p in collaboration.periods.all()}
        contributors = {self._slug(c.name): c for c in collaboration.contributors.all()}
        skip = set(options["skip"])

        wanted = options["period"]
        if wanted and wanted not in periods:
            raise CommandError(f"No period {wanted!r} in {collaboration.slug!r}.")

        loaded = skipped = out_of_bounds = 0

        for plant_dir in sorted(data_dir.iterdir()):
            if not plant_dir.is_dir():
                continue
            if plant_dir.name in skip:
                skipped += 1
                continue
            contributor = contributors.get(plant_dir.name)
            if contributor is None:
                continue

            for metric_code, metric in metrics.items():
                csv_path = plant_dir / f"{metric_code}.csv"
                if not csv_path.exists():
                    continue

                for label, values in self._aggregate(csv_path).items():
                    if wanted and label != wanted:
                        continue
                    period = periods.get(label)
                    if period is None:
                        continue

                    mean = sum(values) / len(values)
                    # Same rule as the API: an out-of-bounds value is REFUSED,
                    # never clamped. Clamping would hide a unit-conversion error
                    # behind a plausible number (DESIGN.md section 3.4).
                    if not metric.is_within_bounds(mean):
                        out_of_bounds += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"  refused {plant_dir.name}/{metric_code} {label}: "
                                f"{mean} outside "
                                f"[{metric.lower_bound}, {metric.upper_bound}]"
                            )
                        )
                        continue

                    Submission.objects.update_or_create(
                        contributor=contributor,
                        period=period,
                        metric=metric,
                        defaults={
                            "value": mean,
                            "n_records": len(values),
                            "agent_version": AGENT_VERSION,
                        },
                    )
                    loaded += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{loaded} submissions loaded, {skipped} contributors skipped "
                f"(reserved for the agent), {out_of_bounds} refused as out of bounds."
            )
        )

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _slug(name: str) -> str:
        return name.lower().replace(" ", "-")

    @staticmethod
    def _aggregate(csv_path: Path) -> dict[str, list[Decimal]]:
        """Period -> daily values. The mean of these is what the agent submits."""
        by_period: dict[str, list[Decimal]] = {}
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                by_period.setdefault(row["period"], []).append(Decimal(row["value"]))
        return by_period

    def _get_collaboration(self, slug: str) -> Collaboration:
        try:
            return Collaboration.objects.get(slug=slug, is_active=True)
        except Collaboration.DoesNotExist as exc:
            raise CommandError(f"No active collaboration with slug {slug!r}.") from exc
