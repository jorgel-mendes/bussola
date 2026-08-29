"""S1-16 — OpenDP spike.

Purpose (ADR-0003): confirm or kill OpenDP before it is on Sprint 2's critical
path. Runs standalone -- no Django, no database -- so it can be executed and
re-executed cheaply.

    uv sync --extra dp
    uv run python evaluation/spike_opendp.py

Answers four questions:

1. Does the Context API express OUR privacy unit (contributor-level, one row
   per contributor per period)?
2. Does `summarize()` give an accuracy figure without spending budget?
3. What does a DP quantile actually cost in utility at consortium scale?
4. Is OpenDP viable, or do we fall back to diffprivlib?
"""

from __future__ import annotations

import random
import statistics

import opendp.prelude as dp
import polars as pl

dp.enable_features("contrib")

# Matches the seeded catalog: MJ/t clinker, thermodynamic floor to wet-kiln
# ceiling. See docs/REFERENCES.md.
LOWER, UPPER = 1760.0, 7100.0
TRUE_MEAN, TRUE_SIGMA = 3400.0, 0.14

# Membership is public (SPEC 3.2), so a public upper bound on the contributor
# count leaks nothing and can be declared to OpenDP.
MAX_LENGTH = 1000


def make_cohort(n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        v = TRUE_MEAN * pow(2.718281828, rng.gauss(0, TRUE_SIGMA))
        vals.append(min(max(v, LOWER), UPPER))
    return vals


def candidates(count: int, lo: float = LOWER, hi: float = UPPER) -> list[float]:
    """Grid derived from the metric's PUBLIC bounds, never from the data."""
    step = (hi - lo) / (count - 1)
    return [lo + step * i for i in range(count)]


def dp_quantile(values: list[float], alpha: float, epsilon: float,
                n_queries: int, grid: list[float]) -> float:
    ctx = dp.Context.compositor(
        data=pl.LazyFrame({"value": values}),
        privacy_unit=dp.unit_of(contributions=1),
        privacy_loss=dp.loss_of(epsilon=epsilon),
        split_evenly_over=n_queries,
        margins=[dp.polars.Margin(max_length=MAX_LENGTH)],
    )
    q = ctx.query().select(pl.col("value").dp.quantile(alpha, grid))
    return float(q.release().collect().item())


def true_quantile(values: list[float], alpha: float) -> float:
    s = sorted(values)
    pos = alpha * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def q1_scale_report() -> None:
    print("=" * 72)
    print("Q1/Q2  Privacy unit and summarize()")
    print("=" * 72)
    vals = make_cohort(12, seed=1)
    ctx = dp.Context.compositor(
        data=pl.LazyFrame({"value": vals}),
        privacy_unit=dp.unit_of(contributions=1),
        privacy_loss=dp.loss_of(epsilon=1.0),
        split_evenly_over=3,
        margins=[dp.polars.Margin(max_length=MAX_LENGTH)],
    )
    q = ctx.query().select(pl.col("value").dp.median(candidates(200)))
    summary = q.summarize(alpha=0.05)
    print("  unit_of(contributions=1)  accepted: yes")
    print("  summarize() without spending budget: yes\n")
    print(summary)
    print("\n  NOTE: 'accuracy' is null for the exponential mechanism. OpenDP")
    print("  reports the mechanism SCALE but no accuracy interval for quantiles.")
    print("  Consequence for S2-5: the 'accurate to +/-X' UI cannot be driven by")
    print("  summarize() for quantiles. It must come from our own simulation.")


def q3_utility_sweep() -> None:
    print("\n" + "=" * 72)
    print("Q3  What does a DP median actually cost? (median, 3 queries/release)")
    print("=" * 72)
    trials = 60
    print(f"\n  Median absolute error, MJ/t clinker -- {trials} trials/cell")
    print("  Sector spread for scale: true IQR is roughly 700 MJ/t\n")
    eps_values = [0.5, 1.0, 2.0, 5.0, 10.0]
    n_values = [12, 25, 50, 100, 250]
    print("      N |" + "".join(f"{e:>10}" for e in eps_values))
    print("  " + "-" * 60)
    for n in n_values:
        row = f"  {n:5d} |"
        for eps in eps_values:
            errs = []
            for t in range(trials):
                vals = make_cohort(n, seed=1000 + t)
                truth = true_quantile(vals, 0.5)
                got = dp_quantile(vals, 0.5, eps, 3, candidates(200))
                errs.append(abs(got - truth))
            row += f"{statistics.median(errs):10.0f}"
        print(row)
    print("\n  Reference: the whole candidate grid spans 5340 MJ/t, so an error")
    print("  above ~1300 (a quarter of the range) is indistinguishable from noise.")


def q3b_grid_sensitivity() -> None:
    print("\n" + "=" * 72)
    print("Q3b  Does a tighter candidate grid help? (N=50, eps=2, 3 queries)")
    print("=" * 72)
    trials = 60
    print("\n  Grid spans are PUBLIC choices, so narrowing them is legitimate")
    print("  only if justified from domain knowledge, not from the data.\n")
    grids = [
        ("full bounds 1760-7100", candidates(200, 1760.0, 7100.0)),
        ("BAT-centred 2500-5000", candidates(200, 2500.0, 5000.0)),
        ("tight 2900-4500", candidates(200, 2900.0, 4500.0)),
    ]
    for label, grid in grids:
        errs = []
        for t in range(trials):
            vals = make_cohort(50, seed=2000 + t)
            truth = true_quantile(vals, 0.5)
            got = dp_quantile(vals, 0.5, 2.0, 3, grid)
            errs.append(abs(got - truth))
        print(f"  {label:26s} median abs error {statistics.median(errs):7.0f} MJ/t")


def q4_verdict() -> None:
    print("\n" + "=" * 72)
    print("Q4  Verdict")
    print("=" * 72)
    print("""
  PROCEED with OpenDP. The Context API expresses our privacy unit directly,
  the mechanisms work, and the constraints found here are properties of
  differential privacy at small N -- not of the library. diffprivlib would hit
  the same wall with weaker guarantees.

  Blockers found and resolved during this spike:

    1. OpenDP 0.15.1 embeds the Polars 1.36.1 DSL schema. Polars 1.43 fails
       with "can't deserialize DSL with incompatible schema". Polars is now
       pinned to >=1.36,<1.37 across hub and agent.
    2. summarize() requires pyarrow, which OpenDP does not declare. Added to
       the `dp` extra.
    3. Quantile queries require a Margin(max_length=...). Legitimate for us:
       membership is public (SPEC 3.2), so a public row-count bound leaks
       nothing.

  Carried into Sprint 2 planning:

    4. summarize() returns NO accuracy interval for the exponential mechanism
       (scale only). Story S2-5 must derive the confidence interval by
       simulation instead of reading it from OpenDP.
    5. Utility at N=12 is poor at any defensible epsilon. See the sweep above.
       The minimum-contributor threshold may need to rise well above 5 for
       quantiles to mean anything, and that is a product decision, not a
       technical one.
""")


if __name__ == "__main__":
    q1_scale_report()
    q3_utility_sweep()
    q3b_grid_sensitivity()
    q4_verdict()
