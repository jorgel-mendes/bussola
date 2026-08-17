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
