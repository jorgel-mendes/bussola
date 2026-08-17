# Design & Testing Document

**Bússola — Privacy-Preserving Benchmarking Platform**
Quantic MSSE Capstone · Jorge Luis dos Santos Mendes
Status: **Sprint 1 of 3** · Last updated: Sprint 1

> This document is a required deliverable. It records design and architecture
> decisions with reasons, patterns used and why, deployment options with cost
> implications, and all testing carried out. It is updated at the end of each
> sprint rather than written at the end of the project.

---

## 1. Problem and Solution Overview

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

### Sprint 1 status

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
| **Strategy + Registry** (Sprint 2) | `privacy/mechanisms/` | One class per statistic type, selected from the catalog, so adding a statistic is a registration rather than an `if/elif` chain. |
| **Append-only ledger** (Sprint 2) | `budget.LedgerEntry` | Auditability. Entries are never updated or deleted. |
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

**95 tests passing at end of Sprint 1.** Lint (`ruff`) clean.

Several tests defend **privacy invariants** rather than mere correctness, and
their docstrings say which invariant and why — so a future change that breaks
one fails with an explanation rather than a red dot.

### 4.1 Categories

| Category | Location | Count | Purpose |
|---|---|---|---|
| Model constraints | `hub/catalog/test_models.py`, `hub/ingest/test_models.py` | 18 | DB-level enforcement of bounds ordering, rationale presence, submission uniqueness, positive record counts |
| API / authentication / tenancy | `hub/ingest/test_submissions_api.py` | 24 | Token rejection paths, plant-identity-from-token, idempotency, bounds rejection, period state |
| Contract | `hub/ingest/test_contract.py` | 8 | Agent DTO ↔ hub serializer, asserted structurally (field sets) rather than by one happy example |
| Benchmark computation | `hub/benchmarks/test_selectors.py` | 11 | Quartiles on a hand-checkable series, suppression threshold, sector isolation, quartile assignment |
| Agent — local compute | `agent/tests/test_compute.py` | 13 | Period filtering, missing data, bounds check and its error message |
| Agent — HTTP client | `agent/tests/test_client.py` | 9 | The retryable/non-retryable split per status code |
| Agent — CLI | `agent/tests/test_cli.py` | 9 | Exit codes, dry-run sends nothing, local failure precedes network call |
| Naming drift | `hub/test_naming_drift.py` | 51 | Enforces the frozen domain vocabulary. Verified to fail on a planted violation rather than pass vacuously. |

### 4.2 Notable tests and why they exist

- **`test_resubmission_updates_in_place`** — defends the sensitivity bound. If
  this fails, the privacy guarantee is void, not merely inconvenient.
- **`test_contributor_is_taken_from_token_not_body`** — injects a foreign
  contributor id into the payload and asserts it is ignored.
- **`test_cannot_submit_against_another_collaborations_metric`** — the tenancy
  boundary. A foreign metric code must be indistinguishable from a nonexistent
  one, so the response does not reveal what other groups measure.
- **`test_ack_field_names_match_the_hub_serializer`** — added after the
  `plant`→`contributor` rename broke exactly this boundary at runtime.
- **`test_raw_token_is_never_stored`** — a database dump must not yield usable
  credentials.
- **`test_out_of_bounds_value_is_rejected_not_clamped`** — pins the decision in
  §3.4 so a future "helpful" clamp cannot be added silently.
- **`test_dry_run_sends_nothing`** — asserts the submissions endpoint is *never
  called*, not merely that output looks right. Dry-run is the feature that earns
  operator trust; it must be provably inert.
- **`test_other_cohorts_do_not_leak_into_a_benchmark`** and
  **`test_refuses_to_compute_across_collaborations`** — contamination across a
  cohort or a collaboration boundary would be a disclosure, not just a wrong
  number. The latter also protects the Sprint 2 budget from being drawn down by
  the wrong group.
- **`test_agent_payload_fields_match_serializer_fields`** — structural contract
  assertion in both directions, so adding a field to one side without the other
  fails immediately.

### 4.3 Test infrastructure decisions

**CI runs Postgres, not SQLite.** The Sprint 2 budget accountant depends on
`select_for_update()`, which is a **no-op on SQLite** — the concurrency tests
would pass vacuously and the guarantee would be unverified. Local development
may use SQLite for speed; `config.settings.test.using_postgres()` lets tests
that require real row-level locking skip explicitly rather than silently.

**Synthetic data is a methodological requirement, not a convenience.** The
Sprint 2 privacy–utility evaluation measures noisy released statistics against
true ones, so ground truth must be known. `datagen/generate.py` persists
`ground_truth.json` for exactly this. Real plant data would make the evaluation
impossible.

**CI also checks for missing migrations** (`makemigrations --check`) and runs
`manage.py check --deploy --fail-level WARNING` against production settings, so
a security misconfiguration fails the build rather than reaching Render.

### 4.4 Planned for Sprint 2

| Category | Purpose |
|---|---|
| **Concurrency** | K parallel releases against a budget affording K−1; assert exactly one `BudgetExhausted` and `SUM(epsilon) ≤ total`. Requires `TransactionTestCase` and real threads. |
| **Property-based** (`hypothesis`) | Over *random* sequences of release requests, the ledger sum never exceeds the budget. This is the correctness property the system exists to guarantee, so it deserves generated inputs rather than three hand-written cases. |
| **Statistical calibration** | Run each mechanism 10,000 times at fixed ε; assert empirical noise distribution matches theory. Catches the class of bug where code runs, returns plausible numbers, and provides no privacy at all. |
| **Regression** | Golden-file outputs under a fixed seed — in tests only, never in production releases. |

---

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

### Sprint 2 — the privacy core (planned)

OpenDP integration · per-collaboration, per-period epsilon budget · append-only ledger · release
refusal on exhaustion · accuracy estimates before release · budget splitting
across statistics · concurrency and property-based tests.

### Sprint 3 — product surface and evidence (planned)

Plant self-service position view · confidence intervals on every published
value · privacy–utility curve in the dashboard · ledger CSV export · final demo.
