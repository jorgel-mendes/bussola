# Glossary — frozen domain vocabulary

**Status: FROZEN as of end of Sprint 1.**

These nouns changed once, in Sprint 1, while migrations were still throwaway
([ADR-0004](adr/0004-collaboration-as-tenancy-boundary.md)). They do not change
again. `hub/test_naming_drift.py` fails the build if a retired name reappears as
an identifier.

Why freeze: from Sprint 2 the epsilon ledger holds real privacy-accounting
history, and renaming becomes a data-preserving multi-migration exercise. A
half-renamed codebase is also worse than either name applied consistently — the
one rename already caused a real runtime break, when the agent could no longer
parse an acknowledgement whose field had moved.

---

## Core nouns

| Term | Model | Definition |
|---|---|---|
| **Collaboration** | `collaborations.Collaboration` | A set of contributors pooling data under **one privacy budget** and one governance agreement. The tenancy boundary. Carries the operator's identity and kind. |
| **Cohort** | `collaborations.Cohort` | A comparison group within a collaboration. Benchmarks are published per (cohort, metric, period). |
| **Contributor** | `contributors.Contributor` | A party that submits data: a plant, a hospital site, a reporting unit, a firm. |
| **Operator** | `Collaboration.operator_name/_kind` | The organisation running the hub — the **trusted curator**. Association, university, agency, or regulator. |
| **MetricDefinition** | `catalog.MetricDefinition` | What is measured, with its DP-critical parameters: bounds, bounds rationale, privacy unit, statistics. Scoped per collaboration. |
| **ReportingPeriod** | `ingest.ReportingPeriod` | The window a submission belongs to. Scoped per collaboration. |
| **Submission** | `ingest.Submission` | One contributor's aggregate for one metric in one period. |
| **Agent** | `agent/bussola_agent` | The program a contributor runs locally. Computes the aggregate; submits only that. |
| **Hub** | `hub/` | The central service. The trusted curator's software. |

## Privacy terms

| Term | Meaning |
|---|---|
| **Privacy unit** | One contributor's total contribution to one period. `dp.unit_of(contributions=k)`. |
| **Privacy budget / epsilon** | Total permitted disclosure for one collaboration in one period. |
| **Bounds** | Clamping range from **public or domain knowledge — never from the data.** |
| **Bounds rationale** | The required justification for those bounds. Displayed to contributors. |
| **Suppression** | Refusing to publish a cell below `Collaboration.min_contributors`. |
| **Release** | Publishing a protected statistic. Spends budget; writes a ledger entry. |
| **Central DP / trusted curator** | Noise applied at the hub, not the agent ([ADR-0002](adr/0002-central-dp-over-local-dp.md)). |

---

## Retired — do not reintroduce

| Retired | Use instead | Why |
|---|---|---|
| `Plant` | `Contributor` | Industrial-specific; the platform is domain-neutral |
| `Sector` | `Cohort` | Same |
| `plants` (app) | `contributors` | Same |
| `PlantTokenAuthentication` | `ContributorTokenAuthentication` | Same |
| `plant_position()` | `contributor_position()` | Same |
| `MIN_CONTRIBUTORS` as the authority | `Collaboration.min_contributors` | The setting survives only as a deployment-wide floor |
| `SubmissionAck.plant` | `SubmissionAck.contributor` | Wire contract; broke the agent once already |
| `BUSSOLA_PLANT_LABEL` | `BUSSOLA_CONTRIBUTOR_LABEL` | Agent config |

### What is deliberately *not* frozen

Demo **data** stays industrial. Seeded contributors are named `Plant 01`, their
data directories are `plant-01/`, and `datagen` generates cement and chemical
plant profiles. That is the worked example, not the domain model — a concrete
demonstration beats an abstract one, and the process-physics bounds rationales
are the part a generic benchmarking product cannot produce.

The distinction the drift test enforces: **retired names are banned as
identifiers, permitted inside string literals.**

---

## Naming rules for new code

1. **Never** name a domain concept after one vertical. If a name only makes
   sense for factories, it is wrong.
2. Anything scoped to a tenant takes a `collaboration` FK, and its natural key
   is unique *per collaboration*, not globally.
3. Anything that spends privacy budget names the collaboration and period it
   spends against.
4. A new vertical must be reachable by adding catalog rows — never by adding a
   model.
