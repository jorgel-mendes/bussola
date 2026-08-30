# Bússola

**Privacy-preserving benchmarking platform**
Quantic MSSE Capstone · Jorge Luis dos Santos Mendes

[![CI](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml/badge.svg)](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml)

| Deliverable | Status |
|---|---|
| **Task board** (Trello) | [Bussola — MSSE Capstone](https://trello.com/b/ZMEqk4Up/bussola-msse-capstone) ✅ public |
| **Design & testing doc** | [`docs/DESIGN.md`](docs/DESIGN.md) ✅ |
| **Deployed version** | Sprint 1 runs locally. Render blueprint is committed (`render.yaml`); URL goes here when deployed. |
| **Demo recording** | One per sprint — record Sprint 1 even though it is local |

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

> ### ⚠ Sprint 1 status
> This build publishes **exact, unprotected statistics** behind a warning banner.
> It exists to prove ingestion, deployment and CI end to end. Differential
> privacy arrives in Sprint 2. **Do not point this build at real plant data.**

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

### Django apps

| App | Sprint | Responsibility |
|---|---|---|
| `collaborations` | 1 | Collaborations, cohorts, operator identity |
| `contributors` | 1 | Contributors, hashed API tokens |
| `catalog` | 1 | Metric definitions — bounds, rationale, privacy unit |
| `ingest` | 1 | Reporting periods, submissions, the API |
| `benchmarks` | 1 | Aggregation and the dashboard |
| `privacy` | 2 | OpenDP mechanism wrappers |
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

144 tests as of Sprint 1. Several defend **privacy invariants** rather than mere
correctness, and say so in their docstrings — notably submission idempotency (a
contributor that submits twice would double its weight and break the sensitivity
bound the guarantee rests on), contributor-identity-from-token, and the
cross-collaboration tenancy boundary.

CI runs against **Postgres, not SQLite**: the Sprint 2 budget accountant relies
on `select_for_update()`, which is a no-op on SQLite, so those tests would pass
vacuously.

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

## Sprint 1 scope

**Done:** domain model with DB-level constraints · `Collaboration` tenancy ·
token auth · ingestion API · agent CLI with dry-run · synthetic data with ground
truth · exact benchmark dashboard · admin console · CI · Docker · Render
blueprint.

**Deliberately deferred to Sprint 2:** OpenDP integration · privacy budget
ledger · accuracy intervals · anything cryptographic.

A thin slice that reaches production beats a thick slice that doesn't.
