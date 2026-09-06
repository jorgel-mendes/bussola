# Bússola

**Privacy-preserving benchmarking platform**
Quantic MSSE Capstone · Jorge Luis dos Santos Mendes

[![CI](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml/badge.svg)](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml)

| Deliverable | Status |
|---|---|
| **Deployed version** | <https://bussola-hub.onrender.com> ✅ live |
| **Task board** (Trello) | [Bussola — MSSE Capstone](https://trello.com/b/ZMEqk4Up/bussola-msse-capstone) ✅ public |
| **Design & testing doc** | [`docs/DESIGN.md`](docs/DESIGN.md) ✅ |
| **Sprint reviews** | [Sprint 1](docs/SPRINT-1-REVIEW.md) ✅ · [Sprint 2](docs/SPRINT-2-REVIEW.md) ✅ |
| **Demo recording** | One per sprint; the final 15–20 minute video is an edit of the three |

---

## Why this exists

In my chemical engineering degree, almost every question worth researching
needed real plant data. We almost never got it — and not because companies were
hostile. Several were willing. Nobody could give them a safe way to say yes, so
the default answer became no and the research didn't happen.

That wall isn't a student problem. It's the same one that stops an industry
association answering *"how does my plant compare?"*, stops hospitals pooling
results across sites, and stops a statistical agency publishing without exposing
respondents. Four buyers, one blocker.

The blocker is that **trust is currently a contract, not a control**. The answer
today is a confidentiality agreement and a promise — and under LGPD a promise is
not something a compliance officer can sign off.

**Bússola replaces the promise with a proof.** Contributors submit aggregates
through an agent that runs on their own machine; raw data never leaves the site.
The operator publishes group statistics protected by differential privacy. Every
unit of privacy spent is written to an append-only ledger an auditor can
inspect — so the guarantee is checkable rather than asserted.

### Who operates it

Whoever the contributors already trust: an industry association, a university's
data-governance office, a statistical agency, a sector regulator. They already
have the members, the mandate and the relationship — what they lacked was a
mechanism. `Collaboration` models that tenancy and records which kind of operator
it is, because the guarantee is only as strong as that existing trust
([ADR-0004](docs/adr/0004-collaboration-as-tenancy-boundary.md)).

### Why the small end

Large players solved this for themselves — Catena-X across the German automotive
value chain, MELLODDY across ten rival pharma companies (all ten ended up with
better models), and "data clean room" is now a Gartner category served by AWS,
Snowflake and Decentriq. Those are built for enterprises with legal teams and
seven-figure budgets; MELLODDY spent $1.19M on compute in a single year. A
regional federation, a university research group, or a twelve-plant consortium
has the same problem and no product.

The seeded demo is industrial: cement plants, specific thermal energy, bounds
justified from process thermodynamics and the EU BAT reference document
([docs/REFERENCES.md](docs/REFERENCES.md)).

---

## What this build does

Every statistic the dashboard publishes is **differentially private**. Quartiles
are released with the exponential mechanism over a candidate grid derived from
the metric's public bounds — never from the submitted data. Each release charges
its epsilon to an append-only ledger inside the same database transaction that
writes the release, and a release that would exceed the reporting period's budget
is **refused** rather than served.

Three things follow, and they are the product:

- **No exact value is reachable anywhere in the UI.** The Sprint 1 exact path
  survives only in tests and in the before/after demo comparison.
- **A release and its ledger entry cannot exist without each other.**
  `LedgerEntry.release` is `NOT NULL`, the write is one transaction, and the
  invariant is asserted in both directions.
- **The system says when its own answer is unusable.** See below.

### When the answer is too noisy to use

Each quantile is drawn independently, so at small N the noise can exceed the
spacing between them and the ordering inverts. On the deployed hub, a six-
contributor cohort released a third quartile *below* its first:

| Cohort | N | q25 | median | q75 | |
|---|---|---|---|---|---|
| `2011` | 50 | 3048.0 | 3718.9 | 4175.1 | usable |
| `2320` | 47 | 3155.4 | 3370.1 | 4309.2 | usable |
| `2farm` | 6 | **158.5** | 190.9 | **73.4** | **q75 below q25** |

It reproduced across three seeds, so it is a property of the mechanism at that
scale rather than a fluke. `BenchmarkRelease.quantiles_are_ordered` detects it
without touching the data, and the dashboard tells the member the release is too
noisy to use.

It is deliberately **not** fixed by sorting. Sorting would be privacy-safe —
differential privacy is closed under post-processing — but it would conceal the
one signal telling a member not to trust the release, replacing a visibly broken
number with an invisibly meaningless one.

---

## Architecture

```
Agent (contributor 01) ─┐
Agent (contributor 02) ─┼─ HTTPS + bearer token ─→  Hub (Django) ─→ Dashboard
Agent (contributor NN) ─┘                           Postgres
```

The **agent** is a separate installable package with no Django dependency. That
is what makes the multi-party architecture real rather than cosmetic: each
contributor runs an independent program, with its own credential, that reads only
its own data.

| Component | Location | Role |
|---|---|---|
| `hub/` | Django 5 + DRF | Ingestion, catalog, aggregation, dashboard, admin |
| `agent/` | standalone CLI | Reads local CSV, computes aggregate, submits |
| `contracts/` | pydantic | The single wire-format definition both sides import |
| `datagen/` | script | Synthetic multi-plant data **with ground truth** |
| `evaluation/` | pytest → CSV | The privacy–utility sweep (SPEC §8) |

### Django apps

| App | Sprint | Responsibility |
|---|---|---|
| `collaborations` | 1 | Collaborations, cohorts, operator identity |
| `contributors` | 1 | Contributors, hashed API tokens |
| `catalog` | 1 | Metric definitions — bounds, rationale, privacy unit |
| `ingest` | 1 | Reporting periods, submissions, the API |
| `benchmarks` | 1–2 | Aggregation, the DP release path, the dashboard |
| `privacy` | 2 | OpenDP mechanism strategies and their registry |
| `budget` | 2 | Epsilon budget and the append-only ledger |

---

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync
uv run python hub/manage.py migrate
uv run python hub/manage.py seed_demo --contributors 12 --periods 24 --tokens-out data/tokens.json
uv run python datagen/generate.py --contributors 12 --periods 24 --out data
uv run python hub/manage.py runserver
```

Then submit as a plant:

```bash
export BUSSOLA_HUB_URL=http://127.0.0.1:8000
export BUSSOLA_TOKEN=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['plant-01'])")
uv run bussola-agent submit --metric specific_thermal_energy --period 2026-07 \
  --file data/plant-01/specific_thermal_energy.csv --dry-run
```

Drop `--dry-run` to actually submit. The dashboard is at <http://127.0.0.1:8000/>,
the admin at `/admin/` (`createsuperuser` first).

### Publish a differentially private release

Check what a release would cost before spending anything:

```bash
uv run python hub/manage.py release_period --collaboration bahia-industry --period 2026-07 --epsilon 1.0 --dry-run
```

`--dry-run` reports the cells it would publish and the statistics it would skip,
and **spends no budget** — epsilon, once spent, cannot be refunded, so the
operator guide is emphatic about running this first. Drop the flag to publish:

```bash
uv run python hub/manage.py release_period --collaboration bahia-industry --period 2026-07 --epsilon 1.0
```

The command reports every cell it published, every cell it suppressed for having
too few contributors, and — when the period's budget runs out — the cell it
REFUSED, what it needed, and what is actually left after the rollback. Each cell
is its own transaction: a cell that cannot be paid for never undoes cells already
published, because those are real disclosures the ledger has to keep.

### Multi-party demo

```bash
docker compose up --build hub
docker compose run --rm seed
docker compose up agent-01 agent-02 agent-03
```

Three containers, three volumes, three tokens, one network boundary.

---

## Tests

```bash
uv run pytest
uv run pytest --cov --cov-report=term-missing
uv run ruff check .
```

**280 tests, 83% coverage**, zero skips on Postgres. Several defend **privacy
invariants** rather than mere correctness, and say so in their docstrings —
notably submission idempotency (a contributor that submits twice would double its
weight and break the sensitivity bound the guarantee rests on),
contributor-identity-from-token, and the cross-collaboration tenancy boundary.

Test categories added in Sprint 2: concurrency (K parallel releases on real
threads against real Postgres), property-based (`hypothesis` over random release
sequences), mechanism/statistical, release-invariant, immutability, and an
environment guard.

CI runs against **Postgres, not SQLite**: the budget accountant relies on
`select_for_update()`, which is a no-op on SQLite, so those tests would pass
vacuously. `hub/test_postgres_guard.py` fails the build if they skip instead of
running — a silent skip would reduce the project's most important test to a green
tick that proves nothing.

The suite takes ~11 minutes on CI, most of it OpenDP releases in the mechanism
tests. That cost is deliberate and was accepted rather than trimmed.

---

## Agent exit codes

The agent runs unattended from cron, so exit codes are its real interface:

| Code | Meaning | Action |
|---|---|---|
| 0 | Submitted | — |
| 1 | Config or local data problem | Operator must intervene |
| 2 | Hub rejected the data (401/422) | Do not retry unchanged |
| 3 | Transient (network, 409, 5xx) | Retry later |

---

## Status

**Sprint 1 — the pipeline.** Domain model with DB-level constraints ·
`Collaboration` tenancy · token auth · ingestion API · agent CLI with dry-run ·
synthetic data with ground truth · exact benchmark dashboard behind an UNSAFE
banner · admin console · CI · Docker · Render blueprint.

**Sprint 2 — the guarantee.** Quantile mechanisms behind a Strategy + Registry ·
per-period epsilon budget · append-only ledger · budget refusal · suppression
below the contributor threshold · release and ledger in one transaction ·
per-contributor value list deleted · deployed to Render. Reviewed in
[`docs/SPRINT-2-REVIEW.md`](docs/SPRINT-2-REVIEW.md).

**Sprint 3 — the evidence (in progress).** The privacy–utility sweep · accuracy
intervals by simulation · the privacy–utility curve in the dashboard ·
contributor self-service position view · ledger CSV export for the auditor.

### Deliberately not built

| | Why |
|---|---|
| Count, mean and standard deviation mechanisms | Far worse value per unit of epsilon. At ε = 1 split three ways, a DP mean's interval came back wider than the sum being estimated. Shipping only the statistic that works is a position, not a gap |
| zCDP accountant | Basic composition can be checked with a calculator and explained on camera. `BudgetPeriod.accountant` carries the choice and refuses loudly rather than mis-accounting |
| Anything cryptographic | Central DP with a trusted curator is the architecture, and it is argued in [ADR-0002](docs/adr/0002-central-dp-over-local-dp.md) rather than assumed |

A thin slice that reaches production beats a thick slice that doesn't.
