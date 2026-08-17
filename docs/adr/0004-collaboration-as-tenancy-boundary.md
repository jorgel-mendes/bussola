# ADR-0004 — Collaboration as the tenancy boundary

**Status:** Accepted · Sprint 1 (supersedes the association-only framing in ADR-0002)

## Context

The system was first designed for a single buyer: an industry association
benchmarking its member plants. The domain model said so — `Plant`, `Sector` —
and there was one implicit tenant.

Two questions forced a re-examination.

**Could the buyer be an individual industrial company?** Mostly no, and the
reason is instructive. If one company owns all the sites, there is no adversary:
the company already holds every row, and differential privacy would be
protecting it from itself. The privacy machinery only earns its place when the
contributing parties do not trust each other. Narrow exceptions exist —
multinationals with data-residency rules between subsidiaries, joint ventures,
works-council restrictions on cross-site data — but they are not a foundation.

**Could the buyer be a university or research institute?** Yes, and better than
the association. The trusted-curator role is *institutionalised* in research: a
data governance office or ethics committee exists precisely to hold sensitive
data neutrally on behalf of parties who will not share it directly. Multi-site
studies, hospital consortia and pooled survey microdata have the same shape as
member plants. Statistical agencies are the canonical case — the 2020 US Census
is this architecture at national scale.

The generalisation: **the buyer is whoever occupies the neutral seat.** An
association is one occupant, not the only one.

## Decision

Introduce **`Collaboration`** as an explicit tenancy boundary, and rename the
domain to be neutral:

| Was | Now |
|---|---|
| *(implicit single tenant)* | `Collaboration` |
| `Sector` | `Cohort` |
| `Plant` | `Contributor` |

A *collaboration* is a set of contributors pooling data under one privacy budget
and one governance agreement. The term is not invented here: AWS Clean Rooms and
Decentriq both use it for this exact unit.

`Collaboration` carries `operator_name` and `operator_kind`
(association / university / agency / regulator), because the guarantee offered
to contributors depends on who the curator is — see §Consequences.

## Consequences

### The privacy budget now has a correct scope

A single global epsilon budget was always going to be wrong once one deployment
hosted more than one group. Sprint 2's budget hangs off
`Collaboration × ReportingPeriod`, so two unrelated groups cannot draw down each
other's privacy budget.

### `min_contributors` moves from settings to the model

A 12-plant consortium and a 400-hospital study need different suppression
thresholds, and one deployment may host both. The Django setting survives as a
deployment-wide floor.

### A new security boundary, with tests

Metric codes and period labels are now unique *per collaboration*, not globally.
That creates a cross-tenant leak surface that did not previously exist, so it is
tested explicitly:

- an agent cannot submit against another collaboration's metric or period;
- the metric catalog lists only the caller's own collaboration, so enumeration
  does not reveal what other groups measure;
- a request for a foreign metric returns "unknown", indistinguishable from a
  code that does not exist at all;
- `Submission.clean()` refuses a row whose contributor, period and metric do not
  share one collaboration;
- `compute_exact_benchmark()` raises rather than computing across collaborations.

### `operator_kind` is recorded, not decorative

The hub operator sees raw submissions before noise is applied (ADR-0002). The
guarantee is therefore only as strong as the contributors' existing reason to
trust *this particular operator*. Recording who that is — and displaying it on
every benchmark page — makes the dependency explicit rather than implied.

### Timing

Done in Sprint 1, deliberately. Migrations were regenerated from scratch because
the data was throwaway. After Sprint 2 the ledger holds real epsilon history and
this becomes a data-preserving multi-migration exercise — not something to
attempt solo in week 10.

### What did not change

The agent. It sends a metric code and a period label; both are resolved
server-side within the collaboration derived from its token. The agent never
knew about sectors and does not need to know about collaborations.

The demo stays industrial — cement plants, energy intensity, thermodynamic
bounds. The model is domain-neutral, but an abstract "Contributor A submitted
Metric 1" demonstration is far worse to watch, and the process-physics rationale
is the part a generic benchmarking product cannot produce.
