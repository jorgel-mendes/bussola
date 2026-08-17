# Sprint 1 Review & Next Steps

For Jorge · end of Sprint 1 · 95 tests passing, 89% coverage, ruff clean

This is an honest handover: what needs your judgment, what I could not verify,
what I would change, and what Sprint 2 looks like. Items are ordered by cost of
getting them wrong.

---

# A. Decide these before writing more code

> **A1 and A2 are now RESOLVED** (see §A0). A3 still wants your sign-off.

## A0. What changed after the first review

**A1 — fixed.** `contributions_per_period` is now **1**, with `help_text`
spelling out that it counts *rows added to the table the hub runs DP over*, not
underlying observations. Migration `catalog/0002`.

**A2 — researched and replaced.** The invented bounds are gone. Both seeded
metrics now trace to citable sources, recorded in
[REFERENCES.md](REFERENCES.md):

| Metric | Bounds | Anchor |
|---|---|---|
| `specific_thermal_energy` (MJ/t **clinker**) | 1 760 – 7 100 | Thermodynamic floor (+1 761 kJ/kg reaction enthalpy) to wet-kiln ceiling (5.3–7.1 GJ/t). EU BAT-AEL band 2 900–3 300 quoted for reference — Commission Implementing Decision 2013/163/EU, BAT 6, Table 1. |
| `specific_electrical_energy` (kWh/t **cement**) | 60 – 200 | Survey literature, 92–141 kWh/t typical. **No BAT-AEL exists** — the EU instrument gives techniques only (BAT 10). |

`specific_water_use` was dropped: I could not source it defensibly, and one
sourced metric beats two where one is invented.

The denominators now differ deliberately (clinker vs cement) and are carried in
`MetricDefinition.unit`, displayed on every published statistic. Mixing them is
the classic cement-benchmarking error.

**Still yours to verify:** whether *your* target contributors report thermal
energy per tonne of clinker (the convention these bounds assume) or per tonne of
cement. If the latter, divide by the clinker factor — around 0.75 globally.

---

## A1. `contributions_per_period` — RESOLVED, but understand why

**Kept here because the reasoning matters more than the fix.**

The catalog declares `contributions_per_period = 30`, described as "how many
underlying records one contributor supplies per period". That maps to OpenDP's
`dp.unit_of(contributions=k)`.

But look at what actually reaches the hub. The agent reads 30 daily records,
computes their **mean**, and submits **one value**. The table the hub runs DP
over therefore has *one row per contributor* — 12 rows for 12 contributors.

Removing one contributor removes **one row**, not thirty. So the privacy unit is
`contributions=1`.

Why it matters: for a bounded sum, sensitivity is `k × (U − L)`. Declaring
`k = 30` when the true value is 1 inflates sensitivity thirtyfold, and therefore
the noise. At ε = 1 on a 720 kWh/t range that is the difference between a usable
benchmark and pure noise. You would spend Sprint 2 debugging a utility problem
that is actually a modelling error.

**What I think is correct:**

- `contributions_per_period = 1` — one submitted row per contributor per period.
- `Submission.n_records = 30` stays as it is. It records how many observations
  underlie the value, which is useful for weighting and for the audit trail, but
  it is **not** the privacy unit.

**But confirm the intent first**, because there is a real alternative design: the
agent could submit all 30 raw daily records and let the hub do everything. That
would make `contributions=30` correct — and would also mean raw per-day data
leaves the plant, which is most of what the product exists to prevent. I do not
think you want it, but it is your call, and the field's `help_text` should say
which model you chose.

**Applied:** `contributions_per_period = 1` everywhere, with the field's
`help_text` stating the distinction so the next person cannot repeat the error.
If you later move to submitting raw per-record data, this value must change with
it — that coupling is now documented on the field itself.

## A2. Bounds — RESOLVED, now sourced

`bounds_rationale` is the showpiece feature: the thing that demonstrates domain
expertise no generic product has. Which makes the numbers behind it the worst
possible place to be wrong, in front of an audience that includes chemical
engineers.

The original figures were invented and, as suspected, wrong: 180–900 kWh/t was
labelled "electrical" when published electrical figures sit at 92–141 kWh/t.

Replaced with sourced bounds (§A0) and `datagen` re-centred to match — synthetic
plants now generate around 3 400 MJ/t clinker with a right tail into the
4 000s, so the sector looks like a real one where a minority sit above the BAT
band. Verified end to end: 12 contributors submitted, quartiles came out
Q1 3 325 / median 3 368 / Q3 3 642 MJ/t clinker, and the dashboard renders the
EU decision number and the thermodynamic floor in the rationale panel.

**One genuinely nice consequence for the design document:** the two metrics now
carry *different classes* of justification — one anchored in a legal instrument,
one in survey literature — and the rationale text says so. That distinction is
the kind of thing that reads as real domain command rather than decoration.

## A3. Sign off the vocabulary (now frozen)

`Collaboration` / `Cohort` / `Contributor` are frozen, enforced by
`hub/test_naming_drift.py` and documented in [GLOSSARY.md](GLOSSARY.md). I
verified the guard fails on a planted violation rather than passing vacuously.

Last cheap moment to object. Specifically:

- **"Cohort"** — correct in research, slightly odd in industry, where "sector"
  or "peer group" reads more naturally. I chose it for neutrality. If your
  audience is mostly industrial, "peer group" is defensible.
- **"Bússola"** — still a placeholder. Renaming the repo is cheap now and
  annoying after CI, Render and the Trello board reference it.

---

# B. Verify — things I could not run

| # | What | Why it matters | Command |
|---|---|---|---|
| B1 | **Docker builds** | Never executed; your daemon was off. CI builds both images, so this is the most likely first red build. | `docker build -f deploy/Dockerfile.hub .` then `-f deploy/Dockerfile.agent .` |
| B2 | **`docker compose` multi-party demo** | The three-agent demo is a Sprint 1 acceptance criterion and has only been proven with local processes, not containers. | `docker compose up --build hub` → `docker compose run --rm seed` → `docker compose up agent-01 agent-02 agent-03` |
| B3 | **Test suite on Postgres** | Everything local ran on SQLite. CI uses Postgres. Constraint behaviour and transaction semantics differ. | `DATABASE_URL=postgres://... uv run pytest` |
| B4 | **A real Render deploy** | `render.yaml` and `check --deploy` pass, but no deploy has happened. Cold starts, `ALLOWED_HOSTS`, static files and free-Postgres expiry all surface only on contact. | Deploy the current build once, even if you keep working locally |

B3 is the one people skip. The Sprint 2 concurrency tests are meaningless
without it — `select_for_update()` is a no-op on SQLite.

---

# C. Read these files with a critical eye

## C1. `hub/benchmarks/views.py` — the deliberate leak

The `<details>` block publishes **every contributor's individual value**. It is
Sprint 1 scaffolding, labelled as such, and it exists so the pipeline is visibly
working.

It is also precisely what the product exists to prevent. It must be deleted in
Sprint 2 — card `S2-12`, tagged `privacy-critical`. Read it now so you remember
it is there.

## C2. `hub/ingest/views.py` — the 409/422 split

The claim: 409 means transient (retry later), 422 means the data is wrong (never
retry unchanged). The agent's exit codes depend on this. Check you agree with
the mapping, because changing it later changes cron behaviour at every
contributor site.

## C3. `hub/ingest/models.py` — `Submission.clean()`, rule 3

Cross-collaboration integrity is enforced in `clean()`, not by a database
constraint, because enforcing it in the schema would mean denormalising
`collaboration` onto `Submission`. That is a real trade-off: `clean()` does not
run on `Model.objects.create()`.

The API path is safe (it resolves metric and period within the caller's
collaboration), and `compute_exact_benchmark()` raises independently. But a
future bulk-import that skips `full_clean()` would slip past. Decide whether you
want the denormalised column plus a `CheckConstraint` in Sprint 2.

## C4. `hub/collaborations/models.py` — `effective_min_contributors`

Falls back to the `MIN_CONTRIBUTORS` setting when the model value is falsy.
Since the field has `default=5` and is non-null, the fallback only triggers on an
explicit 0. Is 0 a legitimate "no suppression" setting, or should it be
forbidden? Right now it silently becomes 5.

## C5. `agent/bussola_agent/compute.py` — `local_mean`

The agent always submits the mean. For quartile benchmarks that is reasonable,
but it means a contributor's within-period variability is invisible. If you ever
want to publish a dispersion statistic, the agent has to send more than one
number, and that changes the privacy unit (see A1).

---

# D. Known gaps — accepted for Sprint 1, decide when they land

None of these are bugs. They are deliberate omissions you should be able to name
if a grader asks "what would you do differently in production?"

| Gap | Risk | Suggested sprint |
|---|---|---|
| **No rate limiting** on the ingestion API | A leaked token can submit unboundedly. Low impact (idempotent writes), but it is the obvious question. | 3, or name as future work |
| **Tokens never expire** | Long-lived credentials at contributor sites. Revocation exists; rotation is manual. | Future work |
| **Admin is not tenant-scoped** | Any Django staff user sees *all* collaborations. Fine for a single-operator deployment, wrong for true multi-tenancy. | Name explicitly in DESIGN.md as a limitation |
| **Metric list is unpaginated** | Fine at ~10 metrics. The agent's `fetch_metric` handles both bare lists and paginated `{"results": ...}`, so adding pagination will not break it. | Not needed |
| **No structured audit log** beyond Django's admin `LogEntry` | The Auditor actor deserves better than admin history. | 2, alongside the epsilon ledger |
| **`datagen` keeps `PlantProfile` / `sector_code` internally** | Deliberate — it generates industrial demo data. Cosmetic inconsistency only. | Leave it |

---

# E. Rest of Sprint 1

Ordered. The first three are cheap and unblock everything else.

1. **A2** — fix the bounds numbers and rationale text *(≈1 hour, highest value)*
2. **A1** — decide `contributions_per_period` and update the field + `help_text`
3. **B1/B2** — start Docker, verify both images and the three-agent demo
4. **Trello board** — create, make **Public**, paste the cards from
   [TRELLO_CARDS.md](TRELLO_CARDS.md), move Sprint 1 cards to Done *as you review them*
5. **GitHub** — push, share with `quantic-grader`, fix the `USERNAME` badge, confirm CI green
6. **B3** — run the suite once against Postgres
7. **`S1-16` OpenDP spike** — the checklist in TRELLO_CARDS.md. Ends in a
   decision: proceed with OpenDP or fall back to `diffprivlib`. **Do not let this
   slip into Sprint 2 — it is the thing that de-risks Sprint 2.**
8. **Record the Sprint 1 demo** — even though it is local

---

# F. Sprint 2 — the privacy core

**Goal:** every published statistic is differentially private, every epsilon
spend is recorded in an append-only ledger, and no release can exceed its
collaboration's budget for the period.

## F1. Decisions to make in sprint planning

**Composition accountant: basic or zCDP?**
Basic composition (ε adds linearly) is simpler to explain and to audit — a real
advantage for the demo and the Auditor actor. zCDP gives materially better
utility for many queries. `BudgetPeriod.accountant` already carries the choice.
Recommendation: **ship basic first**, add zCDP only if the evaluation shows you
need it. An accountant you can explain on camera beats one you cannot.

**Budget allocation across statistics.** A release of q25 / median / q75 / count
is four queries. Even split via `split_evenly_over=4`, or weighted toward the
statistics contributors care about? Even split first.

**Behaviour on exhaustion.** When the budget is gone mid-period: refuse and
raise (current design), or serve the last valid release? Refusing is correct and
demos better — *"the system declines rather than leaking"* is a strong moment.

**Are releases immutable snapshots?** Yes. `BenchmarkRelease` +
`ReleasedStatistic` store the noisy value and its accuracy interval. Never
recompute a published release — re-running the mechanism on the same data spends
budget again and produces a different number.

## F2. Week-by-week

**Week 1 — mechanisms**
`privacy/mechanisms/` with the Strategy + Registry pattern: one class per
statistic type, selected from `MetricDefinition.statistics`. Wrap OpenDP's
`Context`. Quantiles via the exponential mechanism over a candidate grid derived
from the public bounds; count via discrete Laplace; mean as sum ÷ count with the
budget split. **Statistical calibration tests here, not later** — run each
mechanism 10 000 times at fixed ε and assert the empirical noise matches theory.
That is the test category that catches "runs fine, returns plausible numbers,
provides no privacy".

**Week 2 — the ledger and the accountant**
`BudgetPeriod` (per collaboration × period) and append-only `LedgerEntry`.
`spend()` inside `transaction.atomic()` with `select_for_update()`. Then the two
tests that matter most in the whole project:

- **concurrency** — K parallel releases against a budget affording K−1; assert
  exactly one `BudgetExhausted` and `SUM(epsilon) ≤ total`. Needs
  `TransactionTestCase`, real threads, and **Postgres**.
- **property-based** (`hypothesis`) — over *random* sequences of release
  requests, the ledger sum never exceeds the budget.

Enforce append-only with a `pre_save` guard and an overridden `delete()`, and
test that too.

**Week 3 — wire the release path**
Replace `compute_exact_benchmark` with the DP path. Non-negotiable invariant:
**the `release()` call and the `LedgerEntry` write happen in one transaction.**
A release recorded without a ledger entry is unaccounted privacy loss — the one
bug in this system that is genuinely serious.

Store the accuracy interval from `.summarize(alpha=0.05)` on every
`ReleasedStatistic`. Keep the suppression threshold in front of the DP path.

**Week 4 — surface, and delete the leak**
`S2-12`: remove the per-contributor `<details>` block. Show every published value
with its confidence interval. Add the operator-facing "at ε = X, Q3 will be
accurate to ±Y" preview — the strongest single UI moment in the product, and
free, because `summarize()` costs no budget. Record the Sprint 2 demo.

## F3. Sprint 2 definition of done

- [ ] No exact value is reachable anywhere in the UI
- [ ] Every release has a ledger entry; every ledger entry has a release
- [ ] Concurrency and property-based tests green **on Postgres**
- [ ] Calibration tests confirm each mechanism's noise matches theory
- [ ] Budget exhaustion refuses cleanly and is demonstrated on camera
- [ ] Accuracy intervals displayed next to every published statistic
- [ ] DESIGN.md §4 updated with the new test categories

## F4. The trap to avoid

Do not start Sprint 2 by wiring OpenDP into the release path. Start with the
**ledger and accountant**, which are pure Django and fully testable without any
DP at all, then drop the mechanisms in behind them. If OpenDP turns out harder
than the spike suggested, you still have a working budget system and a
defensible story — rather than a half-integrated library and no accounting.

---

# G. Sprint 3 preview

Contributor self-service view (own position vs. cohort) · privacy–utility curve
in the dashboard · ledger CSV export for the Auditor · Render deployment if not
already done · final 15–20 minute demo recording.

The privacy–utility sweep from SPEC §8 is the "above and beyond" evidence. It
needs the ground truth that `datagen` already persists, which is why that was
built in Sprint 1.
