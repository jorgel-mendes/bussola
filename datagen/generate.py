"""Synthetic multi-plant industrial data.

Synthetic data is a *methodological requirement here, not a convenience*: the
Sprint 2 privacy-utility evaluation measures noisy released statistics against
the true ones, so ground truth must be known. Real plant data would make that
measurement impossible.

The generative process is deliberately plausible rather than uniform:

* each plant has its own long-run mean, drawn lognormally, so the sector
  distribution is right-skewed the way real efficiency distributions are;
* a seasonal term, because kiln and boiler loads track ambient temperature;
* occasional excursions, so the pipeline meets outliers before production does.

Usage:
    python datagen/generate.py --contributors 12 --periods 24 --out data/
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_SEED = 20260811


@dataclass(frozen=True)
class PlantProfile:
    """The hidden truth about a plant. Never sent to the hub — used only to
    score the evaluation in Sprint 2."""

    slug: str
    name: str
    sector_code: str
    true_mean: float
    volatility: float


@dataclass(frozen=True)
class MetricProfile:
    code: str
    unit: str
    sector_mean: float
    sector_sigma: float
    lower_bound: float
    upper_bound: float
    seasonal_amplitude: float


# Mirrors the seeded catalog. Centres sit inside the EU BAT-AEL band
# (2 900-3 300 MJ/t clinker) with a right tail reaching older, less efficient
# lines -- so the synthetic sector looks like a real one, where a minority of
# plants sit well above the BAT range. See docs/REFERENCES.md.
METRICS = [
    MetricProfile(
        code="specific_thermal_energy",
        unit="MJ/t clinker",
        sector_mean=3400.0,
        sector_sigma=0.14,
        lower_bound=1760.0,
        upper_bound=7100.0,
        seasonal_amplitude=0.04,
    ),
    MetricProfile(
        code="specific_electrical_energy",
        unit="kWh/t cement",
        sector_mean=112.0,
        sector_sigma=0.16,
        lower_bound=60.0,
        upper_bound=200.0,
        seasonal_amplitude=0.05,
    ),
]

SECTORS = [("2320", "Cement and lime"), ("2011", "Basic industrial chemicals")]


def build_plants(n: int, rng: random.Random) -> list[PlantProfile]:
    plants: list[PlantProfile] = []
    for i in range(n):
        sector_code, _ = SECTORS[i % len(SECTORS)]
        # Lognormal: a few inefficient plants sit far above the median, which is
        # what makes quartiles more informative than the mean for benchmarking.
        base = METRICS[0].sector_mean * math.exp(rng.gauss(0, METRICS[0].sector_sigma))
        plants.append(
            PlantProfile(
                slug=f"plant-{i + 1:02d}",
                name=f"Plant {i + 1:02d}",
                sector_code=sector_code,
                true_mean=round(base, 3),
                volatility=round(rng.uniform(0.02, 0.08), 4),
            )
        )
    return plants


def period_labels(count: int, start_year: int = 2025, start_month: int = 1) -> list[str]:
    labels = []
    year, month = start_year, start_month
    for _ in range(count):
        labels.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return labels


def generate_records(
    plant: PlantProfile,
    metric: MetricProfile,
    label: str,
    month_index: int,
    records_per_period: int,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Daily records for one plant, one metric, one period."""
    scale = plant.true_mean / METRICS[0].sector_mean
    centre = metric.sector_mean * scale
    seasonal = 1 + metric.seasonal_amplitude * math.sin(2 * math.pi * month_index / 12)

    rows = []
    for day in range(1, records_per_period + 1):
        value = centre * seasonal * math.exp(rng.gauss(0, plant.volatility))
        if rng.random() < 0.02:  # process excursion
            value *= rng.uniform(1.15, 1.45)
        value = min(max(value, metric.lower_bound), metric.upper_bound)
        rows.append({"period": label, "day": day, "value": round(value, 4)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contributors", type=int, default=12)
    parser.add_argument("--periods", type=int, default=24)
    parser.add_argument("--records-per-period", type=int, default=30)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    plants = build_plants(args.contributors, rng)
    labels = period_labels(args.periods)

    for plant in plants:
        plant_dir = out / plant.slug
        plant_dir.mkdir(exist_ok=True)
        for metric in METRICS:
            rows: list[dict[str, object]] = []
            for idx, label in enumerate(labels):
                rows.extend(
                    generate_records(plant, metric, label, idx, args.records_per_period, rng)
                )
            path = plant_dir / f"{metric.code}.csv"
            with path.open("w", encoding="utf-8") as fh:
                fh.write("period,day,value\n")
                for row in rows:
                    fh.write(f"{row['period']},{row['day']},{row['value']}\n")

    # Ground truth. Sprint 2's evaluation scores noisy releases against this.
    truth = {
        "seed": args.seed,
        "periods": labels,
        "records_per_period": args.records_per_period,
        "plants": [asdict(p) for p in plants],
        "metrics": [asdict(m) for m in METRICS],
        "sectors": [{"code": c, "name": n} for c, n in SECTORS],
    }
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")

    print(f"Wrote {len(plants)} plants x {len(METRICS)} metrics x {len(labels)} periods to {out}/")
    print(f"Ground truth: {out / 'ground_truth.json'}")


if __name__ == "__main__":
    main()
