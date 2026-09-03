"""Seed a demo collaboration: cohorts, contributors, metrics, periods, tokens.

Run this before the demo recording so the dashboard has something on it, and
before `docker compose up` so the agent containers have tokens to use.

    python hub/manage.py seed_demo --contributors 12 --periods 24

The seeded collaboration is deliberately *industrial* -- cement and chemical
plants, energy intensity, thermodynamically justified bounds. The platform is
domain-neutral, but an abstract "Contributor A submitted Metric 1" demo is far
worse to watch, and the process-physics rationale is the part no generic
benchmarking product can produce.

Idempotent: re-running updates rather than duplicating, so it is safe to point
at an existing database.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import MetricDefinition, Statistic, ValueType
from collaborations.models import Cohort, Collaboration, OperatorKind
from contributors.models import ApiToken, Contributor
from ingest.models import PeriodStatus, ReportingPeriod

COLLABORATION = {
    "slug": "bahia-industry",
    "name": "Bahia Industrial Efficiency Benchmark",
    "description": (
        "A benchmarking collaboration among industrial plants in Bahia, Brazil. "
        "Members submit monthly efficiency aggregates and receive protected "
        "sector benchmarks in return."
    ),
    "operator_name": "Federação das Indústrias do Estado da Bahia (FIEB)",
    "operator_kind": OperatorKind.ASSOCIATION,
    "min_contributors": 5,
}

# Bounds carry a rationale from public or domain knowledge, never from the data
# (SPEC section 5.2). Every figure below traces to docs/REFERENCES.md. These are
# the strings contributors read next to their benchmark, so they are written to
# be defensible, not decorative.
#
# Note the two metrics carry DIFFERENT CLASSES of justification -- one anchored
# in a legal instrument, one in literature. That distinction is deliberate and
# is stated in the rationale text itself.
METRICS = [
    {
        "code": "specific_thermal_energy",
        "name": "Specific thermal energy consumption",
        "unit": "MJ/t clinker",
        "value_type": ValueType.CONTINUOUS,
        "lower_bound": "1760.000000",
        "upper_bound": "7100.000000",
        "bounds_rationale": (
            "Lower bound is the theoretical reaction enthalpy of Portland clinker "
            "formation, +1 761 kJ/kg, dominated by calcination of calcium carbonate "
            "(+2 138 kJ/kg). This is a thermodynamic floor: no kiln of any design can "
            "consume less and still produce clinker, so a value below it is a metering "
            "or unit-conversion fault rather than an efficient plant. "
            "Upper bound is the top of the reported wet-process range, 5.3-7.1 GJ/t "
            "clinker, the spread driven by raw meal moisture; US wet-kiln averages of "
            "6.8-7.0 GJ/t sit inside it. This bounds the worst installed technology "
            "still in operation. "
            "For reference, the EU BAT-associated level for a dry process kiln with "
            "multistage preheating and precalcination is 2 900-3 300 MJ/t clinker "
            "(Commission Implementing Decision 2013/163/EU, BAT 6, Table 1). The "
            "clamping bounds are deliberately wider than that band: BAT-AEL describes "
            "what a well-run modern plant achieves, whereas clamping bounds must "
            "contain every plant that could legitimately report. "
            "Denominator is tonnes of CLINKER, not cement. See docs/REFERENCES.md."
        ),
        # One submitted aggregate per contributor per period => one row in the
        # table the hub runs DP over. See docs/REFERENCES.md and the field's
        # help_text; n_records carries the observation count separately.
        "contributions_per_period": 1,
        "statistics": [Statistic.COUNT, Statistic.Q25, Statistic.MEDIAN, Statistic.Q75],
    },
    {
        "code": "specific_electrical_energy",
        "name": "Specific electrical energy consumption",
        "unit": "kWh/t cement",
        "value_type": ValueType.CONTINUOUS,
        "lower_bound": "60.000000",
        "upper_bound": "200.000000",
        "bounds_rationale": (
            "Plant-level surveys report 92-141 kWh/t cement, with modern plants "
            "typically near 110-120 kWh/t. Lower bound of 60 sits below any reported "
            "installation -- finish grinding alone accounts for roughly half of typical "
            "consumption, so a whole-plant figure beneath it is not credible. Upper "
            "bound of 200 leaves margin above the reported maximum. "
            "Unlike the thermal metric, these bounds rest on LITERATURE rather than "
            "law: the EU BAT Conclusions address electrical energy at BAT 10 but "
            "prescribe only techniques (power management, high-efficiency grinding, "
            "improved monitoring, reduced air leaks) and set no numeric BAT-AEL. "
            "Denominator is tonnes of CEMENT, not clinker -- the two differ by the "
            "clinker factor. See docs/REFERENCES.md."
        ),
        "contributions_per_period": 1,
        "statistics": [Statistic.COUNT, Statistic.Q25, Statistic.MEDIAN, Statistic.Q75],
    },
]

COHORTS = [("2320", "Cement and lime"), ("2011", "Basic industrial chemicals")]


class Command(BaseCommand):
    help = "Seed a demo collaboration with cohorts, contributors, metrics, periods and tokens."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--contributors", type=int, default=12)
        parser.add_argument("--periods", type=int, default=24)
        parser.add_argument(
            "--tokens-out",
            type=Path,
            default=None,
            help="Write issued raw tokens to this JSON file (used by docker-compose).",
        )
        parser.add_argument(
            "--no-token-output",
            action="store_true",
            help=(
                "Issue tokens but never emit them. For unattended runs at container "
                "boot, where stdout is a retained deploy log: raw API keys in a log "
                "defeat the point of storing only their hashes. Tokens are re-issued "
                "through the admin when a contributor is actually onboarded."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        collaboration, _ = Collaboration.objects.update_or_create(
            slug=COLLABORATION["slug"],
            defaults={k: v for k, v in COLLABORATION.items() if k != "slug"},
        )
        self.stdout.write(f"Collaboration: {collaboration.name}")
        self.stdout.write(f"  operator: {collaboration.operator_name} ({collaboration.operator_kind})")

        cohorts = {}
        for code, name in COHORTS:
            cohort, _ = Cohort.objects.update_or_create(
                collaboration=collaboration, code=code, defaults={"name": name}
            )
            cohorts[code] = cohort
        self.stdout.write(f"Cohorts: {len(cohorts)}")

        for spec in METRICS:
            MetricDefinition.objects.update_or_create(
                collaboration=collaboration,
                code=spec["code"],
                defaults={k: v for k, v in spec.items() if k != "code"},
            )
        self.stdout.write(f"Metrics: {len(METRICS)}")

        labels = self._period_labels(options["periods"])
        for label in labels:
            year, month = (int(part) for part in label.split("-"))
            starts = date(year, month, 1)
            ends = date(year + (month == 12), (month % 12) + 1, 1)
            ReportingPeriod.objects.update_or_create(
                collaboration=collaboration,
                label=label,
                defaults={"starts": starts, "ends": ends, "status": PeriodStatus.OPEN},
            )
        self.stdout.write(f"Periods: {len(labels)} ({labels[0]} … {labels[-1]})")

        tokens: dict[str, str] = {}
        for i in range(options["contributors"]):
            slug = f"plant-{i + 1:02d}"
            cohort = cohorts[COHORTS[i % len(COHORTS)][0]]
            contributor, _ = Contributor.objects.update_or_create(
                collaboration=collaboration,
                name=f"Plant {i + 1:02d}",
                defaults={"cohort": cohort, "is_active": True},
            )
            # One active token per contributor; re-seeding rotates it.
            contributor.tokens.filter(revoked_at__isnull=True).delete()
            _token, raw = ApiToken.issue(contributor, label="seed_demo")
            tokens[slug] = raw

        self.stdout.write(f"Contributors: {options['contributors']} (each with a fresh token)")

        out: Path | None = options["tokens_out"]
        if options["no_token_output"]:
            self.stdout.write(
                "Raw tokens NOT emitted (--no-token-output). Issue one per "
                "contributor from the admin when onboarding."
            )
        elif out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
            self.stdout.write(self.style.WARNING(f"Raw tokens written to {out} — gitignored."))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Raw tokens (shown once):"))
            for slug, raw in tokens.items():
                self.stdout.write(f"  {slug}: {raw}")

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))

    @staticmethod
    def _period_labels(count: int, start_year: int = 2025, start_month: int = 1) -> list[str]:
        labels, year, month = [], start_year, start_month
        for _ in range(count):
            labels.append(f"{year:04d}-{month:02d}")
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return labels
