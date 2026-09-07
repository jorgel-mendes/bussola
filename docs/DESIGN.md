# Design & Testing Document

**Bússola — Privacy-Preserving Benchmarking Platform**
Quantic MSSE Capstone · Jorge Luis dos Santos Mendes
Status: **Sprint 2 of 3 complete** · Last updated: end of Sprint 2

> This document is a required deliverable. It records design and architecture
> decisions with reasons, patterns used and why, deployment options with cost
> implications, and all testing carried out. It is updated at the end of each
> sprint rather than written at the end of the project.

---

## 1. Problem and Solution Overview

### Origin

This project began with a problem I had as a chemical engineering student:
almost every research question worth asking needed real plant data, and we
almost never got it. Not because companies were hostile — several were willing.
Nobody could give them a safe way to say yes, so the default answer became no.

That gap is the reason the platform is domain-neutral rather than
association-specific. A university research group and an industry federation are
blocked by the same thing.

### The general form

Parties who do not trust each other often need a statistic that can only be
computed from their combined data. An industry association is asked *"how does
my plant compare to others in my sector?"*; a university needs a pooled result
across study sites that will not share microdata; a statistical agency must
publish tabulations without exposing respondents.

Producing the statistic requires contributors to disclose data to competitors or
across governance perimeters. They refuse, and reasonably so: a statistic
computed from few contributors can be reverse-engineered to reveal an individual
contributor's figures. So the statistic either does not exist, or is built from
survey returns that are stale, self-reported and unverifiable.

Bússola replaces the trust-based promise ("we won't tell anyone") with a
mathematical guarantee. Contributors run a local agent that computes an aggregate
and submits only that; the hub publishes cohort statistics protected by
differential privacy; every unit of privacy budget spent is recorded in an
append-only ledger an auditor can inspect.

**The buyer is whoever occupies the neutral seat** — the party contributors
already trust to hold their data: an industry association, a university data
governance office, a statistical agency, a sector regulator. `Collaboration`
models that tenancy explicitly and records which kind of operator it is, because
the guarantee's strength depends on it (§2.3). A single company benchmarking its
own sites is *not* a target: it already owns every row, so there is no adversary.
See [ADR-0004](adr/0004-collaboration-as-tenancy-boundary.md).

The worked example throughout — and in the seeded demo — is industrial
benchmarking, because the domain knowledge behind the bounds rationales is real
and a concrete demonstration beats an abstract one.

### Status

Sprint 1 delivers the **thin slice**: a contributor agent submits over the
network to a deployed hub, and an *exact* cohort benchmark appears on a dashboard
behind an unmissable warning banner. Differential privacy is Sprint 2's entire job.

This ordering is deliberate. Deployment, CI and the ingestion boundary are the
things that sink capstone projects when discovered late; the privacy mathematics
is well-bounded library work that can be added to a proven pipeline. A thin
slice that reaches production beats a thick slice that does not.

---

## 2. Privacy Model

Everything in the architecture follows from this section.

### 2.1 Privacy unit

**One contributor's total contribution to one reporting period.** In OpenDP terms
this is `dp.unit_of(contributions=k)`, where `k` is declared per metric in the
catalog as `contributions_per_period`.

### 2.2 What is and is not protected

**Membership is public.** Contributors join a collaboration openly; the roster
is not secret. Protecting participation would be theatre, and claiming to
protect it would be an overclaim.

**Values are protected.** The guarantee is:

> For any published benchmark, the output distribution is (ε, δ)-indistinguishable
> between the world where contributor *X* reported its true values and the world where
> it reported any other values within the metric's declared bounds.

In plain language for the demo: *you cannot infer any individual contributor's numbers
from the published benchmark, no matter what other data you already hold.*

Being precise here matters. An overclaimed guarantee is a worse defect than a
modest, accurate one.

### 2.3 Trust model — central DP, not local DP

The hub receives **raw** contributor aggregates over an authenticated channel and
applies noise at publication time.

**Reasoning.** Local DP — noising at the agent — degrades as roughly √N relative
to central DP. Apple and Google can absorb that because they have ~10⁸
contributors. At N ≈ 10–50 contributors, local DP produces statistics that are
indistinguishable from noise. The trusted-curator model is what the US Census
Bureau used for the 2020 census, and the collaboration operator is *already* the
institutional trusted curator: holding contributors' data neutrally is its
function. `Collaboration.operator_kind` records which kind it is.

**Residual risk, stated honestly.** The hub operator sees raw submissions.
Mitigations are organisational — access control, admin action logging, audit
trail — not cryptographic. Secure aggregation would remove this residual risk
and is recorded as future work, not claimed as delivered.

This decision has an infrastructure consequence recorded in §7: because the hub
operator is the trusted curator, a real deployment must run in the operator's
own tenant. That rules out a shared multi-tenant SaaS deployment.

### 2.4 Minimum contributor threshold

No release for a (cohort, metric, period) cell with fewer than
`Collaboration.min_contributors` (default 5) contributing parties. This is conventional
statistical disclosure control rather than a DP requirement: it prevents
publishing a "benchmark" that is visibly one or two contributors. Because membership
is public (§2.2), thresholding on the true count leaks nothing.

Implemented and tested from Sprint 1 so the suppression path is exercised
throughout rather than bolted on at the end.

---

## 3. Architecture

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Agent (contrib A)│  │ Agent (contrib B)│  │ Agent (contrib N)│
│  own container   │  │  own container   │  │  own container   │
│  own volume      │  │  own volume      │  │  own volume      │
│  own token       │  │  own token       │  │  own token       │
└────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
         │      HTTPS + bearer token                 │
         └──────────────────┬────────────────────────┘
                            ▼
              ┌───────────────────────────┐
              │        HUB (Django)       │
              │ collaborations·contributors│
              │  ingest · catalog          │
              │  benchmarks · privacy(S2)  │
              │  budget(S2)                │
              │  Postgres · Django admin  │
              └───────────────────────────┘
```

### 3.1 Component boundaries

| Component | Package | Why separate |
|---|---|---|
| Agent | `agent/` (`bussola-agent`) | Installable **without Django**. This is what makes the multi-party claim real rather than cosmetic — the agent is an independent program with its own dependency tree and no database access. |
| Contract | `contracts/` (`bussola-contracts`) | The single definition of the wire format. Both sides import it, so drift is a test failure rather than a production incident. |
| Hub | `hub/` | The trusted curator. |

The agent's Docker image installs from source without the workspace lock,
specifically to prove it carries no hidden dependency on the hub.

### 3.2 Why Django rather than FastAPI

Recorded fully in [ADR-0001](adr/0001-django-over-fastapi.md). Summary:

- The epsilon ledger is a **transactional relational** problem. Concurrent
  releases must not double-spend budget, which is `select_for_update()` inside
  `transaction.atomic()`. Django's ORM makes that critical section three lines.
- **Django admin** is the Consortium Analyst's and Auditor's console for free.
  Solo, that is roughly two weeks not spent building CRUD forms — which is why
  there is no bespoke admin UI anywhere in the backlog.
- **Migrations.** The privacy schema will change repeatedly.
- **Templates** mean one deployable. Adding a React SPA or Streamlit would mean
  two build pipelines and two free-tier services for no rubric benefit.

Acknowledged trade-off: FastAPI offers async I/O and lighter serialisation.
Neither is on the critical path; ledger integrity is.

### 3.3 Patterns used

| Pattern | Where | Why |
|---|---|---|
| **Repository / selectors** | `benchmarks/selectors.py` | Keeps aggregation logic out of views. In Sprint 2 the DP release path replaces the function body without touching the view — the signature was designed to survive that change. |
| **DTO / contract** | `contracts/bussola_contracts` | One definition of the wire format, imported by two independently deployed programs. Enables a real contract test. |
| **Data-driven configuration** | `catalog.MetricDefinition` | Bounds, privacy unit and statistic list are data, scoped per collaboration. Adding a metric is an admin operation, not a code change; changing vertical is a catalog change, not a fork. |
| **Strategy + Registry** | `privacy/mechanisms/` | One class per statistic type, selected from the catalog, so adding a statistic is a registration rather than an `if/elif` chain. |
| **Append-only ledger** | `budget.LedgerEntry` | Auditability. Entries are never updated or deleted. |
| **Twelve-factor config** | `config/settings/` + `django-environ` | The same image runs locally, in CI and on Render. |

### 3.4 Key data-model decisions

**Collaboration is the tenancy and privacy-budget boundary.** Metric codes and
period labels are unique *per collaboration*, not globally, so one deployment can
host an industry consortium and a university study without either seeing the
other. That creates a cross-tenant leak surface, so it is tested explicitly: an
agent cannot submit against another collaboration's metric or period; the catalog
lists only the caller's own metrics; a foreign metric code returns "unknown",
indistinguishable from one that never existed. See
[ADR-0004](adr/0004-collaboration-as-tenancy-boundary.md).

**Metric catalog is the keystone.** `MetricDefinition` drives agent-side
validation *and* hub-side DP mechanism selection. `bounds_rationale` is a
**required** field: OpenDP is strict that clamping bounds must come from public
or domain knowledge, because deriving them from the data leaks. Most
implementations write `# picked (0, 100)`; here the rationale is stored,
required, and displayed to members next to every published benchmark. It turns
a library constraint into visible engineering justification.

**Submission idempotency is a privacy invariant, not data hygiene.** The unique
constraint on `(plant, period, metric)` means a resubmission updates in place.
Without it a plant could submit twice and double its weight in the aggregate,
breaking the per-contributor sensitivity bound the entire guarantee rests on.
Enforced at the database level, because an application-level check is not a
guarantee when data can arrive via a fixture, a shell session, or a future
endpoint that forgets.

**Plant identity comes from the token, never the body.** The submission payload
has no plant field at all. An agent cannot submit on another plant's behalf even
if it tries — there is a test for exactly that.

**Tokens are stored hashed.** Only a SHA-256 hash is persisted; the raw key is
shown once, at issue. Storing raw API keys in a system whose premise is data
protection would be indefensible. SHA-256 rather than a password KDF is
deliberate: tokens are high-entropy random strings, not user-chosen secrets, so
a slow hash would add latency to every API call for no security gain.

**Failed validation rejects rather than clamps.** An out-of-bounds value is
refused with 422, not silently clamped into range. Clamping would hide a sensor
fault or unit-conversion error behind a plausible number, and the operator would
never learn about it.

### 3.5 API status codes

| Code | Meaning | Agent behaviour |
|---|---|---|
| 401 | Bad, revoked or inactive-plant token | Stop; human intervention |
| 409 | Period not open | **Retryable** — transient |
| 422 | Value outside declared bounds | Stop; retrying unchanged never helps |
| 400 | Malformed payload | Stop |

The 409/422 split is the one that matters operationally: the agent runs
unattended from cron and must distinguish "try again in an hour" from "a human
must look at this".

---

## 4. Testing

**275 tests passing at end of Sprint 2** (144 at end of Sprint 1) on Postgres;
269 passing plus 6 correctly skipped on SQLite. Lint (`ruff`) clean.

Several tests defend **privacy invariants** rather than mere correctness, and
their docstrings say which invariant and why — so a future change that breaks
one fails with an explanation rather than a red dot.

### 4.1 The method: plant the defect

The single most useful testing practice in this project is not a category of
test. It is a habit: **after writing a test, break the thing it guards and
confirm it fails.**

Sprint 1 shipped five defects, and three were invisible because *something
still looked fine* — a clean exit code, a plausible number. A test that has
never been observed failing is indistinguishable from a test that cannot fail.

Applied throughout Sprint 2, it found four cases where a test was not testing
what its name claimed:

| Planted defect | Result | What it revealed |
|---|---|---|
| Remove `select_for_update()` from the accountant | Caught — `ledger sums to 0.900000 against a budget of 0.7000` | The concurrency test works; a silent 29% over-release |
| Write the ledger entry *before* the budget check | **Passed** | The refusal test passes because of transaction rollback, not statement order. Rollback was load-bearing and untested, so it got its own tests |
| Accept `remaining × 1.0001` (an off-by-one) | **Passed** | Property-based testing explores the space but never lands on the boundary. Two boundary-targeted properties were added |
| Return the *true* quantile from the mechanism | Caught by 5 tests — but only after the weak test was replaced | See below |

That last one is the important one. The original test compared a released
quantile against the exact one and asserted they differed. **It proved
nothing:** the exponential mechanism selects from a 200-point candidate grid
while the exact quantile interpolates between observed values, so the two
differ *even with no noise applied at all*. It would have passed against a
mechanism providing zero privacy. It was replaced with tests that check
randomness as randomness — 30 releases of identical data must not all agree,
and the spread must widen as epsilon falls.

**The generalisable lesson:** a test that a DP output "looks different from the
true value" is not evidence of privacy. Only variation across repeated releases
is.

### 4.2 Categories

| Category | Location | Purpose |
|---|---|---|
| Model constraints | `catalog/test_models.py`, `ingest/test_models.py`, `budget/test_models.py` | DB-level enforcement of bounds ordering, rationale presence, submission uniqueness, positive epsilon |
| API / authentication / tenancy | `ingest/test_submissions_api.py` | Token rejection paths, contributor-identity-from-token, idempotency, bounds rejection, period state |
| Contract | `ingest/test_contract.py` | Agent DTO ↔ hub serializer, asserted structurally rather than by one happy example |
| **Concurrency** | `budget/test_concurrency.py` | K parallel releases against a budget affording K−1. **Requires Postgres**; skips on SQLite and the build fails if it skips where it should not |
| **Property-based** (`hypothesis`) | `budget/test_properties.py` | Over random sequences of release requests, the ledger sum never exceeds the budget — plus boundary-targeted properties, because random generation does not aim at boundaries |
| **Mechanism / statistical** | `privacy/test_mechanisms.py` | That noise is applied at all, and that its spread responds to epsilon. Catches the defect class where code runs, returns plausible numbers, and provides no privacy |
| **Release invariant** | `benchmarks/test_releases.py` | The release and its ledger entries are written in one transaction, asserted in *both* directions |
| **Immutability** | `budget/test_models.py`, `benchmarks/test_releases.py` | Append-only ledger and immutable releases, including the QuerySet bulk paths that bypass `save()` |
| Dashboard / disclosure | `benchmarks/test_views.py` | That no individual contributor value is reachable, and that viewing spends no budget |
| Agent (compute, HTTP, CLI) | `agent/tests/` | Period filtering, bounds check, the retryable/non-retryable status split, exit codes, inert dry-run |
| Naming drift | `test_naming_drift.py` | Enforces the frozen domain vocabulary. Verified to fail on a planted violation |
| **Environment guard** | `test_postgres_guard.py` | Fails the build when tests that must run were skipped instead |

### 4.3 Notable tests and why they exist

- **`test_k_parallel_releases_against_a_budget_affording_k_minus_one`** — the
  flagship. Two simultaneous releases against a budget with room for one will
  both read "epsilon remaining", both decide they can afford it, and both
  write. Nothing errors, the ledger balances against itself, and the guarantee
  is void. There is no way to catch that by reading code or with a sequential
  test. A `Barrier` is used rather than merely starting threads: without it the
  first finishes before the last starts and the lock is never contended.
- **`test_every_released_statistic_has_a_ledger_entry`** and
  **`test_every_ledger_entry_has_a_release`** — the invariant in both
  directions. A release with no entry is unaccounted privacy loss; an entry
  with no release is a charge for a disclosure nobody received. The first is
  the serious one.
- **`test_rendering_the_page_spends_no_budget`** — if viewing released
  statistics, a refresh would spend epsilon and a crawler would exhaust a
  collaboration's annual allowance in seconds.
- **`test_no_individual_contributor_value_is_reachable`** — the inverted form
  of a Sprint 1 test that *asserted the leak was present*, so that removing it
  had to be a deliberate edit to a documented expectation rather than a silent
  deletion.
- **`test_one_unit_past_the_remaining_budget_is_refused`** — added after a
  planted off-by-one survived every other property.
- **`test_repeated_releases_of_identical_data_do_not_agree`** — the single most
  important assertion about the mechanism. If 30 releases of the same data all
  return the same number, there is no privacy however plausible it looks.
- **`test_the_seeded_split_matches_datagen`** — `seed_demo` and `datagen` carry
  separate copies of the cohort weights. If they drift, the seeded roster and
  the generated data describe different consortia and every benchmark is
  computed over the wrong cohort.
- **`test_an_unimplemented_accountant_raises_rather_than_falling_back`** — a
  zCDP budget accounted as basic composition would report the wrong remaining
  epsilon. A loud refusal beats a plausible wrong number.

### 4.4 Test infrastructure decisions

**CI runs Postgres, not SQLite.** The budget accountant depends on
`select_for_update()`, which is a **no-op on SQLite** — the concurrency tests
would pass vacuously and the guarantee would be unverified.

**A skip is green, and that is the problem.** Skipping the concurrency tests on
SQLite is correct locally. In CI it is a disaster waiting to happen: a mistyped
`DATABASE_URL` or a Postgres service that failed to start would reduce the
project's most important test to four skips and a green tick nobody looks at
again. CI sets `BUSSOLA_REQUIRE_POSTGRES=1` and `test_postgres_guard.py` turns
that silence into a build failure. This is retro action A3 — "treat *looks
fine* as unverified" — expressed as code rather than as an intention.

**Synthetic data is a methodological requirement, not a convenience.** The
privacy–utility evaluation measures noisy released statistics against true
ones, so ground truth must be known. `datagen/generate.py` persists
`ground_truth.json` for exactly this. Real plant data would make the
measurement impossible.

**The demo consortium is deliberately uneven — 50/50/6.** An even split cannot
express "this cell cannot support a release", which is the case the privacy
story most needs to demonstrate and the harder half to fake. See §4.5.

**CI also checks for missing migrations** and runs `manage.py check --deploy
--fail-level WARNING` against production settings.

**Cost, stated:** the suite takes ~9m30s on CI, up from ~1m20s. The mechanism
tests run OpenDP roughly 155 times at ~450 ms per release. Context reuse was
measured and gives no speedup (1.0×) — the cost is in the release itself, not
in building the compositor. Deepening these toward SPEC §7.5's 10,000 trials is
recorded as `S3-9`, and needs its own CI job rather than a tighter loop.

### 4.5 What the tests found that design review did not

The release path was run end to end against the reseeded 106-contributor demo.
Median absolute values, one period, ε = 1.0 per cell:

| Cohort | N | q25 | median | q75 | |
|---|---|---|---|---|---|
| `2011` | 50 | 3182.2 | 3504.2 | 6187.6 | ok |
| `2320` | 47 | 2001.5 | 3423.7 | 4577.6 | ok |
| `2farm` | 6 | **131.8** | 171.9 | **126.1** | **q75 < q25** |

**At N = 6 the released third quartile came out below the first.** Each
quantile is drawn independently by the exponential mechanism, so at small N the
noise exceeds the spacing between them and the ordering inverts. Both
50-contributor cohorts were clean.

This is the ADR-0003 utility floor arriving as a visibly broken number rather
than as a table in a document. `BenchmarkRelease.quantiles_are_ordered` detects
it and the dashboard says the release is too noisy to use.

**It is deliberately not fixed by sorting.** Sorting would be privacy-safe —
differential privacy is closed under post-processing — but it would conceal the
one signal telling a member not to trust the release, replacing a visibly
broken number with an invisibly meaningless one.

### 4.6 Planned for Sprint 3

| Category | Purpose |
|---|---|
| **Statistical calibration at depth** (`S3-9`) | Assert the empirical distribution matches the exponential mechanism's theory, not merely that spread responds to epsilon. Needs its own CI job |
| **Privacy–utility sweep** | SPEC §8, over ε × N × statistic, emitting a CSV that serves both the design document and the results charts |
| **Accuracy intervals** (`S2-5`) | Derived by simulation, since `summarize()` returns none for the exponential mechanism |
| **Regression** | Golden-file outputs under a fixed seed — in tests only, never in production releases |

## 5. CI/CD

GitHub Actions on every push and pull request:

1. `ruff check` — lint
2. `makemigrations --check` — no model/migration drift
3. `manage.py check --deploy` against **production** settings
4. `pytest --cov` against **Postgres**
5. Build both Docker images (hub and agent)

Deployment to Render is driven by `render.yaml`, with a health check at
`/api/v1/healthz/`.

---

## 6. Deployment Options and Cost

| Option | Cost | Suitability |
|---|---|---|
| **Render free tier** | £0 | Capstone deliverable. Cold starts after inactivity; free Postgres expires after a fixed term. Warm `/api/v1/healthz/` before recording the demo. |
| Small VPS (Hetzner/DigitalOcean) | ~$7/mo | Adequate for a real pilot with 10–50 plants. Manual patching and backups. |
| Azure App Service + Postgres Flexible Server | ~$40/mo | Realistic production choice — an industry federation is likely already an Azure tenant, so it inherits existing identity, network and compliance posture. |

**The privacy model constrains the deployment.** Because the hub operator is the
trusted curator (§2.3), a production deployment must run inside the
association's own tenant. A shared multi-tenant SaaS deployment would move the
trust boundary to a third party the members never agreed to trust — so the
cheapest hosting option is architecturally unavailable, which is a direct cost
consequence of a privacy decision.

---

## 7. Architecture Decision Records

| ADR | Decision |
|---|---|
| [0001](adr/0001-django-over-fastapi.md) | Django over FastAPI |
| [0002](adr/0002-central-dp-over-local-dp.md) | Central DP (trusted curator) over local DP |
| [0003](adr/0003-opendp-over-diffprivlib.md) | OpenDP over diffprivlib |
| [0004](adr/0004-collaboration-as-tenancy-boundary.md) | Collaboration as the tenancy boundary |

ADR-0003 carries the **spike outcome**: OpenDP confirmed, with three resolved
blockers (Polars 1.36.1 pin, undeclared `pyarrow`, required `Margin`) and two
findings carried into Sprint 2 planning.

Supporting references: [GLOSSARY.md](GLOSSARY.md) (frozen domain vocabulary,
enforced by `hub/test_naming_drift.py`) and [REVIEW.md](REVIEW.md) (Sprint 1
review, known gaps, Sprint 2 plan).

---

## 8. Sprint Log

### Sprint 1 — thin slice, end to end ✅

**Goal:** a plant agent submits over the network to a deployed hub, and an exact
sector benchmark appears on a dashboard. No differential privacy.

Delivered: domain model with DB-level constraints · `Collaboration` tenancy with
per-collaboration budget scope and cross-tenant tests · hashed token auth ·
ingestion API with 401/409/422 semantics · standalone agent CLI with dry-run ·
synthetic data generator with ground truth · exact benchmark dashboard with
suppression · Django admin console · 94 tests · CI with Postgres · Docker images
for hub and agent · `docker-compose` multi-party demo · Render blueprint.

Mid-sprint the domain was generalised from association-only to any trusted
curator (ADR-0004). Taken deliberately in Sprint 1, while migrations were still
throwaway — after Sprint 2 the ledger holds real epsilon history and the same
change becomes a data-preserving migration exercise.

Deferred by design: OpenDP, budget ledger, accuracy intervals, anything
cryptographic.

**Sprint 1 review and retrospective:** [SPRINT-1-REVIEW.md](SPRINT-1-REVIEW.md).
Five defects shipped and were caught by running things rather than reading them;
the OpenDP spike (`evaluation/spike_opendp.py`) ran before the sprint closed and
surfaced a hard Polars version conflict plus the measured privacy-utility floor.

### Sprint 2 — the privacy core ✅

**Goal:** every published statistic is differentially private, every epsilon
spend is recorded in an append-only ledger, and no release can exceed its
collaboration's budget for the period. **Met.**

Compressed from four weeks to one. The plan was re-cut rather than shaved:
roughly 75% of the original scope was dropped explicitly, and what was dropped
is recorded below rather than left implied.

Delivered: `BudgetPeriod` and append-only `LedgerEntry` · the accountant's
critical section under `select_for_update()` · concurrency and property-based
tests on Postgres · a CI guard that fails when those tests skip · quantile
mechanisms behind a Strategy + Registry · `BenchmarkRelease` and
`ReleasedStatistic` as immutable snapshots · the release and its ledger entries
in one transaction, with `LedgerEntry.release` NOT NULL · suppression ahead of
the DP path · the per-contributor disclosure removed · the dashboard rendering
published releases only · deployment to Render.

**Order was deliberate.** The ledger and accountant were built first, with no
OpenDP anywhere in the tree — pure Django, fully testable without any
differential privacy. If the library had fought us, there would still have been
a working, auditable budget system. (REVIEW §F2's week table says the opposite
and is wrong; see the note there.)

**Two defects found in the surface work, neither in the plan.** The
per-contributor `<details>` block was the known leak. The chart *also* plotted
Minimum and Maximum — two individual contributors' exact values under a
friendlier label. Removing the known leak alone would have left a direct
disclosure in place.

**Cut, and why:**

| Cut | Reason |
|---|---|
| Count, mean and stddev mechanisms | Far worse value per unit of epsilon (SPEC §6.1). At ε=1 split three ways a DP mean's interval came back wider than the sum being estimated. Shipping only the statistic that works is a position, not a gap |
| Accuracy intervals (`S2-5`) | `summarize()` returns none for the exponential mechanism (ADR-0003 finding 4). Needs simulation; deferred to Sprint 3 |
| 10,000-trial calibration (`S3-9`) | ~450 ms per release, and context reuse measured at 1.0× speedup. Needs its own CI job, not a tighter loop |
| zCDP accountant | Basic composition can be checked with a calculator and explained on camera. `BudgetPeriod.accountant` carries the choice and refuses loudly rather than mis-accounting |

**Also delivered, unplanned:** `bootstrap_deploy` (Render's free tier has no
shell, so first-run setup happens at boot), `load_submissions` and
`release_period`, and the unusable-release warning described in §4.5.

**Two defects fixed that the product's own thesis condemned:** `seed_demo`
printed raw contributor API tokens to stdout, which at container boot means a
retained deploy log; and `create_superuser()` bypasses
`AUTH_PASSWORD_VALIDATORS`, so a deploy could stand up an internet-reachable
admin with `admin`/`admin` and report success.

**Carried to Sprint 3:** `S2-5` (accuracy intervals), `S3-9` (calibration
depth), `S1-13` (invite `quantic-grader`).

> **Card numbering corrected in Sprint 3.** These documents called the
> calibration card `S3-8`; on the board `S3-8` is the final recording and
> calibration is `S3-9`. The board is the graded artifact, so the documents
> moved to match it rather than the other way round.

### Sprint 3 — product surface and evidence

**Delivered.** Full review in [SPRINT-3-REVIEW.md](SPRINT-3-REVIEW.md).

| Delivered | Where |
|---|---|
| The privacy–utility sweep (SPEC §8) | `evaluation/sweep.py`; 7,000 releases, 2h47m |
| The curve, and a reading for each release | `benchmarks/utility.py`, the dashboard |
| Accuracy intervals by simulation (`S2-5`) | Inverted onto the true value, clamped to the declared bounds |
| Contributor self-service position (`S3-1`) | `bussola-agent position`; spends no budget |
| Ledger CSV export for the Auditor (`S3-4`) | Running cumulative epsilon; admin action + command |
| Command test coverage (retro `B2`) | `release_period` and `load_submissions`, 0% → 97% |
| Retired vocabulary in the product (`S3-10`) | The agent's `--help` still said "plant" |

**Cut:** `S3-6` (trend across periods) and `S3-9` (10,000-trial calibration
depth). Neither was attempted and abandoned; both were cut at planning, as in
Sprint 2.

**What the sweep changed about the product, not only the documentation.**
SPEC §8's predicted headline — *"at ε=1.0 with 25 plants, 96% of plants are
assigned to the correct quartile"* — measured at **47.6%**. The result that
replaced it is ε·N ≈ 200 as the iso-utility contour, with the counterweight that
epsilon cannot buy its way out of a small cohort: at N=5 the correct-quartile
rate moves only from 36.8% at ε=0.1 to 50.8% at ε=8, and the release is
collapsing every contributor into one quartile rather than misplacing a few.

That is the measured case for two decisions previously argued from theory — the
minimum-contributor suppression threshold, and central DP over local DP
([ADR-0002](adr/0002-central-dp-over-local-dp.md)), since under local DP every
contributor is the small-N regime at N=1.

**The demo releases at ε = 1.0 and says the number out loud.** At that epsilon a
50-contributor cohort places 66.9% of its members correctly, and the dashboard
displays it beside the benchmark. Raising epsilon until the figure flattered the
demo was available and was not taken; ε=1.0 is the value the literature treats
as standard, and therefore the one a reader can compare against.

**Test count and coverage:** 280 → 412 tests, 83% → 93%.
