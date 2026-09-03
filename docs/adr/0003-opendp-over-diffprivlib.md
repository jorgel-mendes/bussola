# ADR-0003 — OpenDP over diffprivlib

**Status:** Accepted · Sprint 1 (integration lands in Sprint 2)

## Context

Sprint 2 needs a differential privacy library. The realistic candidates are
IBM's `diffprivlib`, Google's `differential-privacy`, and `OpenDP` (Harvard/
Microsoft). Recording the choice now, before integration, so the Sprint 2 spike
has a stated hypothesis to test.

## Decision

**OpenDP** (currently v0.15.x), used through its `Context` API. Declared as an
optional extra (`uv sync --extra dp`) so the Sprint 1 build stays fast.

## Consequences

### Reasons for

1. **Proof-carrying framework.** OpenDP composes transformations and
   measurements with formal stability and privacy maps. The type system makes it
   hard to build an unsound mechanism by accident — which matters when a subtle
   error produces plausible-looking numbers and no privacy at all.

2. **Floating-point-safe noise sampling.** Naive Laplace implementations leak
   through floating-point representation; this is a real published attack, not a
   theoretical concern. OpenDP addresses it at the library level.

3. **`Context` handles budget accounting.** `dp.unit_of(contributions=k)`,
   `dp.loss_of(epsilon=...)` and `split_evenly_over` express exactly the
   accounting this project needs, rather than requiring it to be reimplemented.

4. **`summarize(alpha=0.05)` returns an accuracy estimate without spending
   budget.** This is not just convenient — it becomes a product feature: members
   are shown "at ε = 1.0, Q3 is accurate to ±X (95%)" *before* a release is
   made. No commercial benchmarking product exposes that.

5. **`unit_of(contributions=k)` is exactly our privacy unit.** It expresses
   plant-level protection directly, rather than requiring it to be encoded by
   hand.

### Costs, accepted

- **Polars-backed.** The `Context` API works over Polars LazyFrames. Coming from
  PySpark the mental model transfers (lazy evaluation, expression API), but it
  is not pandas. Budget ~2 days.
- **Steep type system.** `SymmetricDistance`, `AbsoluteDistance`,
  `MaxDivergence`, `ZeroConcentratedDivergence` are confusing on first contact.
  Budget 3–4 days. Mitigation: stay in the `Context` API; drop to raw
  Transformation/Measurement chaining only if forced.
- **API moves between minor versions.** Pin the version; verify signatures
  against the docs during the spike rather than trusting examples.

### Risk mitigation

A standalone OpenDP spike is scheduled for **Sprint 1 week 4**, deliberately
before the library is on the critical path. If the learning curve proves worse
than estimated, `diffprivlib` is the fallback — simpler API, weaker guarantees —
and switching costs a day because all DP code sits behind the `privacy` app's
mechanism registry rather than being scattered through views.

---

## Spike outcome (S1-16) — decision confirmed

Run: `uv run python evaluation/spike_opendp.py`

**PROCEED with OpenDP.** The `Context` API expresses our privacy unit directly,
the mechanisms work, and the limits found are properties of differential privacy
at small N — not of the library. `diffprivlib` would meet the same wall with
weaker guarantees.

### Blockers found and resolved

1. **OpenDP 0.15.1 embeds the Polars 1.36.1 DSL schema.** With Polars 1.43
   installed, `Context.compositor` fails: *"can't deserialize DSL with
   incompatible schema"*. Polars is now pinned to `>=1.36,<1.37` in both the hub
   and the agent. This is a real constraint on the whole project — the agent uses
   Polars too — and it is the single most valuable thing the spike surfaced,
   because it would otherwise have appeared in Sprint 2 week 1 as an
   inexplicable FFI error.
2. **`summarize()` requires `pyarrow`**, which OpenDP does not declare. Added to
   the `dp` extra.
3. **Quantile queries require `Margin(max_length=...)`** or fail with
   *"Must know max_length"*. Legitimate here: membership is public
   ([ADR-0004](0004-collaboration-as-tenancy-boundary.md), SPEC §3.2), so a
   public bound on the row count leaks nothing.

### Carried into Sprint 2 planning

4. **`summarize()` returns no accuracy interval for the exponential mechanism** —
   only the mechanism scale (`ExponentialMin`, `accuracy: null`). Story **S2-5**
   assumed the confidence interval could be read from OpenDP. It cannot, for
   quantiles. It must be derived by simulation instead. Re-estimate that card.
5. **Utility at N = 12 is poor at any defensible epsilon.** See below.

### Measured privacy–utility (median, 3 queries per release)

Median absolute error in MJ/t clinker, 60 trials per cell. The true sector IQR
is roughly 700 MJ/t, so an error near or above that is useless.

| N | ε=0.5 | ε=1 | ε=2 | ε=5 | ε=10 |
|---|---|---|---|---|---|
| 12 | 1405 | 792 | 115 | 62 | 14 |
| 25 | 678 | 183 | 54 | 27 | 22 |
| 50 | 151 | 49 | 26 | 11 | 8 |
| 100 | 52 | 26 | 12 | 9 | 7 |
| 250 | 24 | 7 | 6 | 5 | 5 |

Reading it: **at ε = 1 the practical floor is around N = 50.** At N = 12 — the
seeded demo size — ε = 1 produces an error larger than the quantity being
measured. Either the consortium is larger, or epsilon is looser, or quantiles
are not publishable.

This is the project's central trade-off arriving early, with numbers, which is
exactly what the spike was for.

### Confirmed in Sprint 2 implementation

Finding 4 was pinned as an executable test rather than left as prose:
`test_summarize_reports_a_scale_but_no_accuracy_for_quantiles` asserts that
`summarize()` returns a positive scale and a null accuracy. If a future OpenDP
version starts returning an interval for the exponential mechanism, that test
fails — which is the notification we want, because the Sprint 3 simulation work
(`S2-5`) would become unnecessary.

Finding 5 was reproduced in the real release path rather than only in the
spike. At N = 6 the released quartiles came out **out of order** — q25 = 131.8,
q75 = 126.1 — because each quantile is drawn independently and at small N the
noise exceeds the spacing between them. Both 50-contributor cohorts were clean.
The utility floor is therefore not merely a table in this document: it is
detectable in a single release, without reference to the data, and the product
now says so (see DESIGN.md §4.5).

One thing this measurement did **not** support: `summarize()` returns a usable
accuracy figure for the Laplace-backed statistics (count, sum, mean) — only the
exponential mechanism returns null. That narrows `S2-5` to quantiles rather than
to every statistic, which was not clear from the original spike.

### Candidate grid width barely matters

At N = 50, ε = 2: full bounds (1760–7100) → 19 MJ/t; BAT-centred (2500–5000) →
20; tight (2900–4500) → 31. Narrowing the grid does **not** buy accuracy and at
some point costs it. Useful, because it removes the temptation to tighten bounds
toward the observed data — which would have leaked.
