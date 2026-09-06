"""The privacy-utility sweep (SPEC section 8).

This is the project's "above and beyond" evidence and the shared artifact with
the Industry 4.0 article: one CSV that answers, quantitatively, the question a
member actually asks -- *at this epsilon, with this many contributors, can I
trust where the benchmark puts me?*

WHAT MAKES THIS MEASUREMENT VALID

Synthetic data is a methodological requirement, not a convenience. Relative
error cannot be computed without ground truth, and ground truth is exactly what
real plant data would not give us (DESIGN.md section 2.1). The generative
process here mirrors `datagen/generate.py` -- lognormal plant means, so the
cohort is right-skewed the way real efficiency distributions are -- and
`test_sweep.py` asserts the two do not drift apart.

WHAT MAKES IT HONEST

Every step below calls the code the hub ships:

* `privacy.contexts.build_context` -- the same compositor, privacy unit and
  margin a real release runs inside;
* `benchmarks.releases.per_statistic_epsilon` -- the same even split, rounded
  the same way;
* `privacy.mechanisms.get_mechanism` -- the same exponential mechanism;
* `benchmarks.selectors.exact_quantile` -- the same definition of the true
  value the noisy one is scored against;
* `benchmarks.selectors.quartile_of` -- the same rule the dashboard uses to
  place a contributor in a quartile;
* `benchmarks.models.quantiles_ordered` -- the same usability check the
  dashboard shows a member.

A harness that reimplemented any of these would be measuring a system nobody
runs, and would drift silently in the flattering direction, because nobody
re-checks a harness that is producing plausible numbers.

It does NOT touch the database. No budget is spent, no ledger entry is written,
no release row is created: the sweep runs the *mechanism*, not the transaction
around it. That is deliberate -- 7,000 simulated releases must not be
indistinguishable from 7,000 real disclosures in the audit trail.

USAGE

    uv run pytest evaluation -m sweep          # full grid, writes the CSV
    uv run python -m evaluation.sweep --help   # same grid, standalone

DEPENDENT VARIABLES, AND ONE CORRECTION TO THE SPEC

SPEC section 8 lists three: relative error, quartile misassignment rate, and
"rank inversion rate -- the fraction of plant pairs whose relative ordering
flips". The third is not well defined for this product and is not implemented.
A contributor's own value is never noised -- it is their own data, held on their
own machine -- so no DP release can reorder one contributor against another.
What CAN invert is the released triple against itself, and that inversion is
both real and observed (Sprint 2, N=6). So the third variable is measured as the
**unusable-release rate**: how often q25 <= median <= q75 fails to hold.

That is a correction to the SPEC, not a substitution of something easier: the
replacement is the harder number to look at, because it counts the times the
product cannot answer.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from benchmarks.models import QUANTILE_STATISTICS, quantiles_ordered
from benchmarks.releases import per_statistic_epsilon
from benchmarks.selectors import exact_quantile, quartile_of
from catalog.models import MetricDefinition
from privacy.contexts import build_context
from privacy.mechanisms import get_mechanism

#: SPEC section 8, independent variable 1: epsilon for the whole release, split
#: evenly across the three quantiles exactly as `release_benchmark` splits it.
EPSILONS: tuple[Decimal, ...] = (
    Decimal("0.1"),
    Decimal("0.25"),
    Decimal("0.5"),
    Decimal("1.0"),
    Decimal("2.0"),
    Decimal("4.0"),
    Decimal("8.0"),
)

#: OpenDP prints "epsilon should be less than or equal to 5, and is typically
#: less than or equal to 1" for every context built at 8.0. It is a raw stdout
#: notice from the Rust core, not a Python warning, so it cannot be captured --
#: and it is left visible rather than worked around. The library flagging its
#: own upper anchor is evidence, not noise: 8.0 is included precisely BECAUSE it
#: is implausibly weak privacy, to show what the utility ceiling looks like.
#:
#: The pilot suggests the finding this grid exists to establish: at N=5 even
#: epsilon=8 leaves the quartile assignment wrong more often than right, while
#: epsilon=1 at N=100 is close to usable. If that holds over 200 trials, cohort
#: size dominates epsilon -- which is the empirical case for the suppression
#: threshold, and for central DP over local DP (ADR-0002).

#: Independent variable 2. 5 is the suppression threshold -- the smallest cell
#: the product will publish at all -- and 6 is the size at which Sprint 2
#: observed q75 land below q25 on the deployed hub, so the interesting part of
#: the curve is at the left end.
CONTRIBUTOR_COUNTS: tuple[int, ...] = (5, 10, 25, 50, 100)

#: Independent variable 4. Fixed seeds, so a reported figure can be reproduced.
DEFAULT_TRIALS = 200
DEFAULT_SEED = 20260906

#: The generative process, mirroring datagen/generate.py's METRICS[0] and the
#: seeded catalog. Kept as literals rather than imported because datagen/ is a
#: script directory, not a package; test_sweep.py loads it by path and asserts
#: these agree, which is the same technique test_seed_demo.py already uses.
SECTOR_MEAN = 3400.0
SECTOR_SIGMA = 0.14
LOWER_BOUND = Decimal("1760.0")
UPPER_BOUND = Decimal("7100.0")
METRIC_CODE = "specific_thermal_energy"
METRIC_UNIT = "MJ/t clinker"

#: One aggregate per contributor per period, so removing a contributor removes
#: exactly one row. Same value the seeded catalog carries.
CONTRIBUTIONS_PER_PERIOD = 1


def sweep_metric() -> MetricDefinition:
    """An UNSAVED metric carrying the seeded catalog's bounds.

    Unsaved on purpose: `quantile_candidates()` is the only thing the mechanism
    needs from it, and constructing it in memory keeps the whole sweep free of
    the database -- which is what lets it run in CI without Postgres, and what
    guarantees it cannot write a release row or spend a real budget.
    """
    return MetricDefinition(
        code=METRIC_CODE,
        name="Specific thermal energy",
        unit=METRIC_UNIT,
        lower_bound=LOWER_BOUND,
        upper_bound=UPPER_BOUND,
        bounds_rationale=(
            "EU BAT reference document for cement: the BAT-AEL band is "
            "2,900-3,300 MJ/t clinker; the declared range spans older wet-process "
            "kilns to best-in-class dry lines. Public knowledge, never derived "
            "from submitted data."
        ),
        contributions_per_period=CONTRIBUTIONS_PER_PERIOD,
        statistics=list(QUANTILE_STATISTICS),
    )


def sample_cohort(n: int, rng: random.Random) -> list[Decimal]:
    """Draw n contributor aggregates from the datagen generative process.

    Lognormal, matching `datagen.build_plants`: a few inefficient plants sit far
    above the median, which is precisely why quartiles are more informative than
    a mean here -- and why the mean is the statistic DP serves worst.
    """
    values = []
    for _ in range(n):
        value = Decimal(str(SECTOR_MEAN * math.exp(rng.gauss(0, SECTOR_SIGMA))))
        values.append(min(max(value, LOWER_BOUND), UPPER_BOUND))
    return values


# --- measurement -----------------------------------------------------------
#
# Pure functions, unit-tested in test_sweep.py against hand-computed cases.
# These produce the numbers the article reports; a defect here would not crash
# anything, it would publish a wrong finding.


def true_quantiles(values: list[Decimal]) -> dict[str, Decimal]:
    """The exact triple the noisy one is scored against."""
    ordered = sorted(values)
    return {
        "q25": exact_quantile(ordered, 0.25),
        "median": exact_quantile(ordered, 0.50),
        "q75": exact_quantile(ordered, 0.75),
    }


def relative_error(noisy: Decimal, true: Decimal) -> float:
    """|noisy - true| / |true| (SPEC section 8, dependent variable 1)."""
    if true == 0:
        raise ValueError("Relative error is undefined against a true value of zero.")
    return float(abs(noisy - true) / abs(true))


def misassignment_rate(
    values: list[Decimal], true: dict[str, Decimal], noisy: dict[str, Decimal]
) -> float:
    """Fraction of contributors the noisy release puts in the wrong quartile.

    THE BUSINESS-MEANINGFUL NUMBER. A member does not ask "what is the released
    median"; they ask "am I in the top quartile". This counts how often the
    answer changes because of the noise.

    Both sides use `quartile_of`, the dashboard's own rule, so a boundary case
    is resolved identically in the true and noisy assignment.
    """
    if not values:
        raise ValueError("Cannot compute a misassignment rate over no contributors.")
    wrong = sum(
        quartile_of(v, true["q25"], true["median"], true["q75"])
        != quartile_of(v, noisy["q25"], noisy["median"], noisy["q75"])
        for v in values
    )
    return wrong / len(values)


# --- one trial, one cell ---------------------------------------------------


@dataclass(frozen=True)
class TrialResult:
    """One simulated release, scored."""

    epsilon: str
    n: int
    trial: int
    epsilon_per_statistic: str
    true_q25: float
    true_median: float
    true_q75: float
    noisy_q25: float
    noisy_median: float
    noisy_q75: float
    rel_err_q25: float
    rel_err_median: float
    rel_err_q75: float
    misassignment_rate: float
    ordered: bool


def run_trial(*, epsilon: Decimal, values: list[Decimal], trial: int, metric=None) -> TrialResult:
    """Release one cell's quantiles under DP and score them.

    Mirrors `release_benchmark` step for step, minus the database: same split,
    same rounding, same context, same mechanisms, same order.
    """
    metric = metric if metric is not None else sweep_metric()
    statistics = list(QUANTILE_STATISTICS)

    per_statistic = per_statistic_epsilon(epsilon, len(statistics))
    total_charged = per_statistic * len(statistics)

    context = build_context(
        values,
        contributions=metric.contributions_per_period,
        epsilon=total_charged,
        split_evenly_over=len(statistics),
    )

    noisy = {
        statistic: get_mechanism(statistic).release(context, metric, per_statistic).value
        for statistic in statistics
    }
    true = true_quantiles(values)

    return TrialResult(
        epsilon=str(epsilon),
        n=len(values),
        trial=trial,
        epsilon_per_statistic=str(per_statistic),
        true_q25=float(true["q25"]),
        true_median=float(true["median"]),
        true_q75=float(true["q75"]),
        noisy_q25=float(noisy["q25"]),
        noisy_median=float(noisy["median"]),
        noisy_q75=float(noisy["q75"]),
        rel_err_q25=relative_error(noisy["q25"], true["q25"]),
        rel_err_median=relative_error(noisy["median"], true["median"]),
        rel_err_q75=relative_error(noisy["q75"], true["q75"]),
        misassignment_rate=misassignment_rate(values, true, noisy),
        ordered=bool(quantiles_ordered(noisy)),
    )


def run_cell(
    *, epsilon: Decimal, n: int, trials: int = DEFAULT_TRIALS, seed: int = DEFAULT_SEED
) -> list[TrialResult]:
    """Run one (epsilon, N) cell of the grid.

    The RNG is seeded from the cell coordinates, so a cell is reproducible on
    its own -- rerunning a single suspicious cell gives the same data it gave
    inside the full sweep, rather than a fresh draw that hides the disagreement.
    """
    rng = random.Random(f"{seed}-{epsilon}-{n}")
    metric = sweep_metric()
    results = []
    for trial in range(trials):
        values = sample_cohort(n, rng)
        results.append(run_trial(epsilon=epsilon, values=values, trial=trial, metric=metric))
    return results


# --- the grid --------------------------------------------------------------

CSV_FIELDS = list(TrialResult.__dataclass_fields__)


def run_sweep(
    *,
    epsilons=EPSILONS,
    contributor_counts=CONTRIBUTOR_COUNTS,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
    on_cell=None,
) -> list[TrialResult]:
    """Run the whole grid. `on_cell` is called after each cell for progress."""
    results: list[TrialResult] = []
    for epsilon in epsilons:
        for n in contributor_counts:
            cell = run_cell(epsilon=epsilon, n=n, trials=trials, seed=seed)
            results.extend(cell)
            if on_cell is not None:
                on_cell(epsilon, n, cell)
    return results


def write_csv(results: list[TrialResult], path: Path) -> Path:
    """One row per trial, not per cell.

    Per-trial rows let the article recompute any aggregate later -- a median
    error, a 95th percentile, a different quartile rule -- without paying for
    the sweep again. Aggregating at write time would throw that away to save
    a few hundred kilobytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))
    return path


@dataclass(frozen=True)
class CellSummary:
    """What one (epsilon, N) cell says, for the curve and the headline."""

    epsilon: str
    n: int
    trials: int
    median_rel_err_median: float
    mean_misassignment_rate: float
    correct_quartile_rate: float
    unusable_rate: float


def summarize_cell(results: list[TrialResult]) -> CellSummary:
    """Aggregate one cell. `correct_quartile_rate` is the demo headline."""
    if not results:
        raise ValueError("Cannot summarize an empty cell.")
    errors = sorted(r.rel_err_median for r in results)
    misassignment = [r.misassignment_rate for r in results]
    mid = len(errors) // 2
    median_error = (
        errors[mid] if len(errors) % 2 else (errors[mid - 1] + errors[mid]) / 2
    )
    mean_misassignment = sum(misassignment) / len(misassignment)
    return CellSummary(
        epsilon=results[0].epsilon,
        n=results[0].n,
        trials=len(results),
        median_rel_err_median=median_error,
        mean_misassignment_rate=mean_misassignment,
        correct_quartile_rate=1.0 - mean_misassignment,
        unusable_rate=sum(not r.ordered for r in results) / len(results),
    )


def summarize(results: list[TrialResult]) -> list[CellSummary]:
    cells: dict[tuple[str, int], list[TrialResult]] = {}
    for result in results:
        cells.setdefault((result.epsilon, result.n), []).append(result)
    return [summarize_cell(cell) for cell in cells.values()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the privacy-utility sweep.")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path("evaluation/results/sweep.csv"))
    args = parser.parse_args(argv)

    def report(epsilon, n, cell):
        summary = summarize_cell(cell)
        print(
            f"  eps={epsilon} N={n:>3}  "
            f"median rel err {summary.median_rel_err_median:6.3f}  "
            f"correct quartile {summary.correct_quartile_rate:6.1%}  "
            f"unusable {summary.unusable_rate:6.1%}"
        )

    results = run_sweep(trials=args.trials, seed=args.seed, on_cell=report)
    path = write_csv(results, args.out)
    print(f"\n{len(results)} trials written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
