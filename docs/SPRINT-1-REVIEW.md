# Sprint 1 — Review & Retrospective

**Bússola** · Quantic MSSE Capstone · Jorge Luis dos Santos Mendes
Solo project · Sprint 1 of 3 · Closed

---

## 1. Sprint goal — met

> A contributor agent submits over the network to a hub, and an exact cohort
> benchmark appears on a dashboard. No differential privacy.

Met, and exceeded in one respect: the multi-party path was proven with real
Docker containers rather than local processes, which was the stretch item.

Not met in one respect: the hub runs locally, not on Render. That was a
deliberate decision taken mid-sprint, and it is carried into Sprint 2 as
`S3-7`. It is the one piece of scope that slipped.

## 2. Delivered

| # | Story | Evidence |
|---|---|---|
| S1-1 | Metric with bounds and required rationale | `catalog.MetricDefinition`, `bounds_rationale` non-blank enforced |
| S1-2 | Register contributor, issue API token | Admin action; SHA-256 hash stored, raw key shown once |
| S1-3 | `bussola-agent submit` from a contributor machine | Standalone package, no Django dependency |
| S1-4 | Reject duplicate submissions | DB unique constraint on (contributor, period, metric) |
| S1-5 | Open/close a reporting period | 409 on a closed period |
| S1-6 | Exact cohort benchmark behind an UNSAFE banner | Dashboard with Chart.js, suppression path live |
| S1-7 | CI on every push | GitHub Actions green: lint, migrations check, `--deploy` check, pytest on Postgres, both Docker images |
| S1-8 | Synthetic multi-contributor data with ground truth | `datagen/`, persists `ground_truth.json` |
| S1-9 | Multi-party shape via docker-compose | 3 agent containers, separate volumes and tokens, all exit 0 |
| S1-10 | Design & testing document | `docs/DESIGN.md` |
| S1-11 | ADRs | 0001–0004 |
| S1-12 | Trello board | Public, verified via Trello API |
| S1-14 | CI badge | Wired to the real account |
| S1-15 | Docker builds verified | 7/7 checklist; **found 3 defects** |
| S1-16 | OpenDP spike | `evaluation/spike_opendp.py`; verdict recorded in ADR-0003 |

**Carried to Sprint 2:** `S1-13` (invite `quantic-grader` — one command),
`S1-17` (record the Sprint 1 demo).

## 3. Quality

- **144 tests**, 89% coverage, passing on **both SQLite and Postgres**
- `ruff` clean; migrations current; `manage.py check --deploy` clean
- Both container images build; CI green end to end

Test categories worth naming: privacy-invariant tests that state which invariant
they defend, cross-tenant boundary tests, a contract test asserting the agent↔hub
wire format structurally in both directions, and a naming-drift guard that was
itself verified to fail on a planted violation.

## 4. What went well

**Deploying nothing, but wiring CI on day one.** Every defect below was caught by
machinery rather than by a person reading code.

**Writing tests that explain themselves.** Several docstrings name the privacy
invariant at stake. When the `plant`→`contributor` rename broke the agent, the
failure was legible immediately.

**Doing the vocabulary refactor in Sprint 1.** Migrations were still throwaway.
The same change after Sprint 2's ledger would have been a data-preserving
migration exercise.

**Running the spike before the sprint closed.** It found a hard dependency
conflict that would otherwise have opened Sprint 2 with an inexplicable FFI
error.

## 5. What went badly

**Five defects shipped into the repo and were caught late.** All were mine, none
were caught by review, all were caught by actually running things:

1. Agent image — uv workspace source unresolvable outside the workspace
2. Hub image — vendored Chart.js referenced a source map we do not ship
3. `docker compose seed` — YAML folded-scalar indentation silently split the
   shell command; exit status still looked clean
4. `contributions_per_period = 30` — wrong by 30× as a privacy unit
5. Metric bounds invented rather than sourced; the "electrical" figure was out
   by roughly 4×

**The pattern:** three of the five were invisible because *something still
looked fine* — a clean exit code, a plausible number. The lesson is not "test
more", it is **distrust anything that cannot be wrong**.

**Docker went unverified for most of the sprint** because the daemon was off,
and the acceptance criterion was reported as met on the strength of local
processes. It was not met until containers actually ran.

**Scope grew mid-sprint.** The association→collaboration generalisation was not
in the sprint backlog. It was the right call and taken at the right moment, but
it was unplanned work.

## 6. Actions for Sprint 2

| # | Action | From |
|---|---|---|
| A1 | Build the **ledger and accountant before** wiring OpenDP. Pure Django, fully testable without DP. | Spike showed DP has real constraints; do not let them block accounting |
| A2 | Re-estimate **S2-5**: `summarize()` gives no accuracy interval for quantiles. The CI must come from simulation. | Spike finding 4 |
| A3 | Treat **"looks fine" as unverified**. Check exit codes directly, never through a pipe. | Defects 1–3 |
| A4 | Revisit `min_contributors`. At N=12, ε=1 the median error exceeds the IQR. | Spike finding 5 |
| A5 | Deploy to Render **early in Sprint 2**, not Sprint 3. | Only slipped goal |
| A6 | Any number that reaches a contributor's screen needs a **source**, not a plausible value. | Defect 5 |

## 7. The number that shapes Sprint 2

From the spike — median absolute error, MJ/t clinker, against a true sector IQR
of roughly 700:

| N | ε=0.5 | ε=1 | ε=2 | ε=5 |
|---|---|---|---|---|
| 12 | 1405 | 792 | 115 | 62 |
| 50 | 151 | 49 | 26 | 11 |
| 250 | 24 | 7 | 6 | 5 |

**At ε = 1 the practical floor is around N = 50.** The seeded demo has 12
contributors split across 2 cohorts — 6 per cell. Sprint 2 must confront this
directly: either the demo consortium grows, or epsilon loosens, or quantiles are
not publishable at demo scale.

This is the project's central trade-off, arriving with numbers attached before
any of Sprint 2 was built. That is what the spike was for.
