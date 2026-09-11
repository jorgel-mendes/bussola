# Bússola

**A benchmarking platform for groups that can't share their data.**
Quantic MSSE Capstone · Jorge Luis dos Santos Mendes

[![CI](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml/badge.svg)](https://github.com/jorgel-mendes/bussola/actions/workflows/ci.yml)

Companies in a sector all want the know *how do I compare?* but getting it
means sharing your data with someone. Bússola lets companies work together
without anyone seeing anyone else's data — and, unusually, tells you how much to
trust the answer it gives you.

Live at **<https://bussola-hub.onrender.com>**

| Deliverable | |
|---|---|
| Deployed version | <https://bussola-hub.onrender.com> ✅ |
| Task board (Trello) | [Bussola — MSSE Capstone](https://trello.com/b/ZMEqk4Up/bussola-msse-capstone) ✅ public |
| Design & testing doc | [`docs/DESIGN.md`](docs/DESIGN.md) ✅ |
| Sprint reviews | [Sprint 1](docs/SPRINT-1-REVIEW.md) · [Sprint 2](docs/SPRINT-2-REVIEW.md) · [Sprint 3](docs/SPRINT-3-REVIEW.md) ✅ |
| Demo recordings | One per sprint ✅ |
| Evaluation | [`evaluation/RESULTS.md`](evaluation/RESULTS.md) — 7,000 measured releases ✅ |
| Where this goes next | [`docs/FUTURE-BACKLOG.md`](docs/FUTURE-BACKLOG.md) |

---

## Why I built it

In my chemical engineering degree, almost every question worth researching
needed real plant data, and we almost never got it. Not because companies were
hostile but because there wasn't a safe procedure to say yes, so the answer
was frequently no.

This isn't an academic problem. It's the same one that stops hospitals pooling
results across sites and stops a statistical agency publishing without exposing
the people it surveyed.

The reason is that trust today is a contract. You get a
confidentiality agreement and a promise. And under privacy laws, a promise 
isn't something a compliance officer can sign off on.

Bússola replaces the promise with something checkable. Contributors compute
their own numbers locally and send only an aggregate. The operator publishes
group statistics protected by differential privacy. Every unit of privacy spent
gets written to a ledger that can't be edited and can be exported. So an
auditor can verify the guarantee held instead of taking someone's word for it.

### Who runs it

Whoever the members already trust: an industry association, a university's data
office, a statistical agency, a regulator. They have the members and the
mandate and with Bussola the mechanism.

The system models that explicitly. A `Collaboration` records which kind of
operator it is, because the guarantee is only ever as strong as the trust it
sits on ([ADR-0004](docs/adr/0004-collaboration-as-tenancy-boundary.md)).

### Why the small end of the market

The big players solved this for themselves. Catena-X did it across German
automotive, MELLODDY across ten rival pharma companies — and all ten came out
with better models. "Data clean room" is now a Gartner category served by AWS,
Snowflake and Decentriq.

Those are built for enterprises with legal teams and seven-figure budgets;
MELLODDY spent $1.19M on compute in one year. An university research group 
or a twelve-plant consortium has the same problem and no product.

The demo is industrial: cement plants, thermal energy per tonne of clinker, with
bounds taken from process thermodynamics and the EU BAT reference document
([docs/REFERENCES.md](docs/REFERENCES.md)).

The choice form industrial was made because of my inspiration and background
and physical based boundaries were easier to test.

---

## What it does

Every number on the dashboard is differentially private. Quartiles come from the
exponential mechanism, using a candidate grid built from the metric's public
bounds — never from the submitted data.

Each release charges its epsilon to an append-only ledger, in the same database
transaction that writes the release. If a release would go over the period's
budget, it's refused rather than served.

Three things follow from that:

- **No exact value is reachable anywhere in the UI.**
- **A release and its ledger entry can't exist without each other.** It's one
  transaction, the foreign key is `NOT NULL`, and tests assert it in both
  directions.
- **The system tells you when its own answer is useless.** Which is the part
  worth explaining.

### When the answer is too noisy to use

Each quartile is drawn independently. In a small cohort the noise can be wider
than the gaps between them, and the order breaks. Here's a real release from the
deployed hub:

| Cohort | N | q25 | median | q75 | |
|---|---|---|---|---|---|
| `2011` | 50 | 3048.0 | 3718.9 | 4175.1 | usable |
| `2320` | 47 | 3155.4 | 3370.1 | 4309.2 | usable |
| `2farm` | 6 | **158.5** | 190.9 | **73.4** | q75 below q25 |

Six contributors, and the third quartile came out below the first. It happened
across three separate seeds, so it's how the mechanism behaves at that size, not
bad luck.

I could sort those three numbers. It would even be safe to do — differential
privacy survives post-processing. But it would hide the one signal telling a
member not to rely on this release, and swap a visibly broken number for an
invisibly meaningless one. So the dashboard shows them as they came out, and
says the release can't be used.

---

## Try it

You'll need [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync
uv run python hub/manage.py migrate
uv run python hub/manage.py seed_demo --contributors 12 --periods 24 --tokens-out data/tokens.json
uv run python datagen/generate.py --contributors 12 --periods 24 --out data
uv run python hub/manage.py runserver
```

The dashboard is at <http://127.0.0.1:8000/>, the admin at `/admin/` (run
`createsuperuser` first).

### Submit as a contributor

```bash
export BUSSOLA_HUB_URL=http://127.0.0.1:8000
export BUSSOLA_TOKEN=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['plant-01'])")
uv run bussola-agent submit --metric specific_thermal_energy --period 2026-07 \
  --file data/plant-01/specific_thermal_energy.csv --dry-run
```

`--dry-run` shows exactly what would leave the machine. Drop it to actually send.

### Publish a release

Always check the cost first. Epsilon can't be refunded once it's spent:

```bash
uv run python hub/manage.py release_period --collaboration bahia-industry --period 2026-07 --epsilon 1.0 --dry-run
```

Then drop `--dry-run` to publish. The command reports what it published, what it
suppressed for having too few contributors, and — if the budget runs out — which
cell it refused and what's left. Cells already published stay published; a cell
that can't be paid for doesn't undo them.

### Ask where you sit

This is the question a member actually joined to have answered, and it runs on
their own machine with their own credential:

```bash
uv run bussola-agent position --metric specific_thermal_energy --period 2026-07
```

```
your value  : 3664.849613 MJ/t clinker
benchmark   : q25=3182.211055  median=3262.713568  q75=3772.562814
              from 47 contributors, ε=1.000002

You are in Q3.
```

It costs nothing. The hub reads a release that was already published and paid
for, and puts your own number against it — that's post-processing, so no budget
is spent. Safe to run on a schedule, and there's a test that hits it ten times
and checks the ledger doesn't grow.

If the release came out in the wrong order, it won't guess:

```
Your position cannot be reported.

This release is too noisy to place you against. The published quartiles came
back out of order, which happens when a cohort is small enough that the privacy
noise exceeds the spacing between them.
```

### Audit the budget

```bash
uv run python hub/manage.py export_ledger --collaboration bahia-industry --period 2026-07
```

Every spend, in order, with a running total next to the authorised budget on each
row. Epsilon adds up linearly here, so that column *is* the accounting — you can
see whether the budget was ever exceeded without doing any arithmetic. The
command won't report success if it wrote fewer rows than the ledger holds.

### The multi-party demo

```bash
docker compose up --build hub
docker compose run --rm seed
docker compose up agent-01 agent-02 agent-03
```

Three containers, three volumes, three tokens, one network boundary.

---

## How it's put together

```
Agent (contributor 01) ─┐
Agent (contributor 02) ─┼─ HTTPS + bearer token ─→  Hub (Django) ─→ Dashboard
Agent (contributor NN) ─┘                           Postgres
```

The agent is a separate package with no Django dependency. That's what makes the
multi-party story real rather than cosmetic — each contributor runs its own
program, with its own credential, reading only its own files.

| Component | Stack | Role |
|---|---|---|
| `hub/` | Django 5 + DRF | Ingestion, catalog, releases, dashboard, admin |
| `agent/` | standalone CLI | Reads local CSV, computes an aggregate, submits |
| `contracts/` | pydantic | The wire format both sides import |
| `datagen/` | script | Synthetic data, with ground truth |
| `evaluation/` | pytest → CSV | The privacy–utility sweep |

| Django app | Responsibility |
|---|---|
| `collaborations` | Collaborations, cohorts, operator identity |
| `contributors` | Contributors and hashed API tokens |
| `catalog` | Metric definitions — bounds, rationale, privacy unit |
| `ingest` | Reporting periods, submissions, the API |
| `benchmarks` | Aggregation, the release path, the dashboard |
| `privacy` | OpenDP mechanisms and their registry |
| `budget` | Epsilon budget and the append-only ledger |

### Agent exit codes

It runs unattended from cron, so exit codes are its real interface:

| Code | Meaning | What to do |
|---|---|---|
| 0 | Submitted | — |
| 1 | Config or local data problem | Someone has to look at it |
| 2 | Hub rejected the data | Don't retry unchanged |
| 3 | Transient (network, 5xx) | Retry later |

---

## Tests

```bash
uv run pytest
uv run pytest --cov --cov-report=term-missing
uv run ruff check .
```

**412 tests, 93% coverage**, no skips on Postgres.

A good number of them defend privacy properties rather than plain correctness,
and say so in their docstrings — submission idempotency, for instance, because a
contributor that submits twice would count double and break the sensitivity
bound the whole guarantee rests on.

CI runs against Postgres rather than SQLite on purpose: the budget accountant
uses `select_for_update()`, which does nothing on SQLite, so the concurrency
tests would pass while proving nothing. There's a guard that fails the build if
they skip instead of running.

The suite takes about 15 minutes, most of it real OpenDP releases. That cost was
accepted rather than trimmed.

The privacy–utility sweep runs in its own workflow — 7 epsilons × 5 cohort sizes
× 200 trials is roughly two and a half hours, and no one should wait for that on
every push. Its fast tests still run every time, because a test harness whose
own tests never run isn't worth trusting.

---

## What the evidence says

Sprint 3 ran 7,000 real releases through the system's own mechanism and scored
them against known ground truth. Full write-up in
[`evaluation/RESULTS.md`](evaluation/RESULTS.md).

Three points on the grid manage 90%+ correct placement with no unusable
releases: ε=8 at 25 contributors, ε=4 at 50, ε=2 at 100. Each multiplies to 200.

> **To halve the privacy cost, double the cohort.**

And more epsilon can't rescue a small group. At 5 contributors the correct-
quartile rate only moves from 36.8% (ε=0.1) to 50.8% (ε=8) — because at that
size the release isn't misplacing a few members, it's collapsing everyone into a
single quartile.

The demo publishes at **ε=1.0**, where a 50-contributor cohort places 66.9% of
its members correctly. The dashboard says so, right next to the benchmark.

I could have raised epsilon until that read 94% — the sweep tells me exactly
where. I didn't. ε=1.0 is the value the literature treats as standard, so it's
the one a reader can compare against, and the gap is honest future work with a
number attached rather than a vague promise. Tuning a parameter until the demo
looked good would be a strange way to demonstrate a project about replacing
promises with proof.

---

## Where it stands

**Sprint 1 — the pipeline.** Domain model with database-level constraints,
tenancy, token auth, the ingestion API, the agent CLI, synthetic data with
ground truth, an exact-statistics dashboard behind a warning banner, CI, Docker,
and a Render blueprint.

**Sprint 2 — the guarantee.** Quantile mechanisms, per-period epsilon budgets,
the append-only ledger, budget refusal, suppression below the contributor
threshold, release and ledger in one transaction, and the deployment.

**Sprint 3 — the evidence.** The privacy–utility sweep, accuracy intervals
derived from it, the trade-off curve in the dashboard, the contributor position
view, and the ledger export.

### Not built, on purpose

**Mean and standard deviation.** Far worse value per unit of epsilon than
quartiles. At ε=1 split three ways, a DP mean's interval came back wider than the
quantity being estimated. Shipping only the statistic that works is a position,
not a gap.

**A zCDP accountant.** Basic composition can be checked with a calculator and
explained out loud. It's the obvious next upgrade —
[`docs/FUTURE-BACKLOG.md`](docs/FUTURE-BACKLOG.md) has it as the best
utility-per-day item available.

**Anything cryptographic.** Central DP with a trusted curator is the
architecture, argued in
[ADR-0002](docs/adr/0002-central-dp-over-local-dp.md) rather than assumed. What a
two-to-five company deployment would need instead is the first half of the
future backlog.

---

A thin slice that reaches production beats a thick slice that doesn't.
