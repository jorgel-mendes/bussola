# Trello board — reference

**Board:** [Bussola — MSSE Capstone](https://trello.com/b/ZMEqk4Up/bussola-msse-capstone)
**Visibility:** public ✅ (verified via `api.trello.com/1/boards/ZMEqk4Up` —
`permissionLevel: "public"`; `quantic-grader` can open it without an invite)
**Status:** 37 cards created · lists in place · checklists pending

This file mirrors the board so the two do not drift. Update it when the board
changes.

---

## 1. Board structure

Five lists, left to right:

```
Product Backlog    Sprint Backlog    In Progress    Blocked    Done
```

### Labels

Verified against `api.trello.com/1/boards/ZMEqk4Up/labels` rather than
remembered — the planned table and the live board had drifted.

| Label | Colour | Status |
|---|---|---|
| `sprint-1` | green | Created end of Sprint 2. Green was the planned slot and was still free |
| `sprint-2` | **yellow_dark** | Live. Note: a blank plain-`yellow` label also exists — do not use it for anything, or the filter menu shows two near-identical yellows |
| `sprint-3` | blue | Live |
| `privacy-critical` | red | Live. A defect here voids the guarantee rather than producing a wrong number |
| `deliverable` | purple | **Planned but never created.** Purple is free if wanted |

## 2. Two paste tricks

**Cards.** Click **+ Add a card**, paste a multi-line block, accept Trello's
offer to create one card per line.

**Checklist items.** Checklists live *inside* a card, not on the board. Open the
card → **Checklist** in the right sidebar (under the **Add** menu in newer
Trello) → name it → then paste all lines at once into the "Add an item" box.
Trello splits them into one item per line, exactly like cards.

---

## 3. Current board state

**44 cards**, read from the API at end of Sprint 2. Lists: Product Backlog ·
Sprint Backlog · In Progress · Blocked · Done.

### Done (34)

All of Sprint 1 (`S1-1` … `S1-17`), plus Sprint 2's delivered work:

```
S2-1  Protect published benchmarks with differential privacy
S2-2  Set a reporting period's epsilon budget
S2-3  Refuse releases that would exceed the budget
S2-4  Record every epsilon spend in an append-only ledger
S2-6  Suppress cells with fewer than five contributors
S2-7  Split budget across the statistics in a release
S2-8  Show the bounds rationale next to each benchmark
S2-9  Write the concurrency test for budget double-spend
S2-10 Write property-based tests for the budget invariant
S2-12 Remove the per-contributor value list from the dashboard
S2-13 Run the concurrency tests locally on Postgres and fail the build if they skip
S2-14 Select DP mechanisms from the catalog via a registry
S2-16 Write the release and its ledger entries in one transaction
S2-17 Assert the release/ledger invariant in both directions
S2-18 Resize the demo consortium to 50/50/6
S2-20 Bootstrap a deployed hub that has no shell access
S3-7  Deploy to Render and add the URL to README
```

`S3-7` was Sprint 1's only slipped goal and was closed on day 1 of Sprint 2,
per retro action A5.

### Product Backlog (10)

```
S2-5  Show an accuracy estimate before releasing          <- cut from Sprint 2
S2-11 Write statistical calibration tests for each mechanism  <- partially done
S3-1  Show a contributor its position against the cohort distribution
S3-2  Show confidence intervals on every published value
S3-3  Put the privacy-utility curve in the dashboard
S3-4  Export the epsilon ledger as CSV
S3-5  Add a dry-run mode note to the operator guide
S3-6  Compare a plant's trend across periods
S3-8  Record the final 15-20 minute demo
S3-9  Deepen the mechanism calibration tests toward 10,000 trials
```

`S2-5` and `S2-11` returned to the backlog rather than being quietly dropped.
Both carry a comment saying why — a card that silently reappears in the backlog
reads as forgotten rather than decided.

**Numbering note:** the calibration card is `S3-9`, not `S3-8`. `S3-8` was
already taken by the final demo recording. This document briefly said `S3-8`
and was wrong; the board was right.

### Known board defects

Two card titles still use **retired vocabulary** (GLOSSARY.md), which the code
forbids and `hub/test_naming_drift.py` enforces:

| Card | Says | Should say |
|---|---|---|
| `S1-3` | "from a **plant** machine" | "from a **contributor** machine" |
| `S3-6` | "Compare a **plant's** trend" | "Compare a **contributor's** trend" |

The board is a graded artifact, so this is worth the two minutes.

## 4. Checklists to add

Only four cards earn one. Don't do this for all 37.

### S1-13 — Push repo and share with quantic-grader · `sprint-1` `deliverable`

```
Push repo to GitHub
Invite quantic-grader as a collaborator
```

Item 1 is done (`github.com/jorgel-mendes/bussola`, CI green). Item 2 is the
only thing blocking the card.

### S1-15 — Verify the Docker builds · `sprint-1`

Add it even though the card is finished: a 7/7 checklist is better evidence than
a card that merely moved. Tick every box, and add a comment recording that this
card found three real defects — that is the card doing genuine work.

```
Start Docker Desktop
docker build -f deploy/Dockerfile.hub .
docker build -f deploy/Dockerfile.agent .
docker compose up --build hub
docker compose run --rm seed
docker compose up agent-01 agent-02 agent-03
Confirm the dashboard shows the suppression message
```

Defects found, all of which had failed or would have failed CI:

1. Agent image — `bussola-contracts = { workspace = true }` cannot resolve
   outside the uv workspace. Fixed with `--no-sources`.
2. Hub image — vendored Chart.js ended with a `sourceMappingURL` pointing at a
   `.map` file we do not ship; WhiteNoise's manifest storage failed during
   `collectstatic`. Comment stripped.
3. `docker compose run seed` — `--tokens-out` sat on a more-indented line inside
   a YAML folded scalar, which YAML keeps literal. The shell command was split,
   so tokens went to stdout instead of the file and `datagen` never ran, while
   the exit status still looked clean.

### S1-16 — Spike OpenDP · `sprint-1`

**The card that de-risks Sprint 2.** [ADR-0003](adr/0003-opendp-over-diffprivlib.md)
states the hypothesis; the spike confirms or kills it while it is still off the
critical path.

```
Install with: uv sync --extra dp
Build a Context over the submissions table
Confirm dp.unit_of(contributions=1) expresses contributor-level privacy
Release a DP median using a candidate grid from the metric bounds
Call summarize(alpha=0.05) and record the accuracy interval
Compare noisy vs true quartiles at epsilon = 0.5, 1, 2
Decide: proceed with OpenDP, or fall back to diffprivlib
```

Note `contributions=1`, not 30. The privacy unit was corrected after the Sprint 1
review — the agent submits one aggregate per period, so one contributor adds one
row to the table the hub runs DP over. See [REVIEW.md](REVIEW.md) §A1.

### S1-17 — Record the Sprint 1 demo · `sprint-1` `deliverable`

Record one per sprint. Three short recordings make the final 15–20 minute video
an edit rather than a performance.

```
Show the metric catalog and the bounds rationale in admin
Issue a token, show it is displayed only once
Run bussola-agent submit --dry-run, then submit
Show idempotency: resubmit, count stays the same
Show a 401 with a revoked token
Show the dashboard, read the UNSAFE banner aloud
Show the suppression path
Show CI green on GitHub
```

Demo the **containerised** version now that it works: three separate agent
containers submitting across a network boundary, then the dashboard suppressing
at 2 contributors (cohorts alternate, so of plants 01–03 only two land in cohort
2320). Considerably stronger than three local processes.

---

## 5. Card renames — retired vocabulary

The domain nouns were frozen in Sprint 1 ([GLOSSARY.md](GLOSSARY.md)) and the
code no longer says *plant* or *sector*. Six card titles still do. The board is
a graded artifact, so it is worth two minutes:

| Card | Rename to |
|---|---|
| S1-2 | Register a **contributor** and issue an API token |
| S1-4 | Reject duplicate submissions (one value per **contributor**/period/metric) |
| S1-6 | Show an exact **cohort** benchmark behind an UNSAFE banner |
| S1-8 | Generate synthetic multi-**contributor** data with ground truth |
| S2-12 | Remove the per-**contributor** value list from the dashboard |
| S3-1 | Show a **contributor** its position against the **cohort** distribution |

The §3 listings above already use the corrected names.

---

## 5b. Deferred — statistical depth (Sprint 3 or post-submission)

Added during Sprint 2 day 3. Recorded here rather than done, because the sprint
is one week and this is the part that can be strengthened later without
invalidating anything built on it.

### S3-9 — Deepen the mechanism calibration tests · `sprint-3`

`hub/privacy/test_mechanisms.py` currently proves the *direction* of the
privacy--utility relationship: repeated releases of identical data disagree,
and the spread widens as epsilon falls. That is enough to catch the defect
class that matters most -- a mechanism that runs, returns plausible numbers and
applies no noise at all -- and it was verified to do so by planting exactly
that bug.

What it does NOT do is check the empirical distribution against theory, which
is what SPEC section 7.5 describes and what the Sprint 2 plan originally scoped
at 10,000 trials per mechanism.

```
Raise trial counts toward the SPEC 7.5 figure (10,000 per mechanism)
Assert the empirical distribution matches the exponential mechanism's theory,
  not merely that spread responds to epsilon
Test q25 and q75 as well as the median
Add the same depth for count and mean when those mechanisms are registered
Move the slow statistical tests to their own CI job or a pytest marker
```

**Why it was cut, honestly:** the trial count is the cost. Each OpenDP release
takes roughly 450 ms, and context reuse was measured and gives no speedup at
all (1.0x) -- the cost is in the release, not in building the compositor. The
current ~155 releases per run already take 9m26s on CI. Ten thousand trials per
mechanism is a separate CI job, not a tighter loop.

**Why cutting it is defensible:** the cheap directional tests catch the
catastrophic failure. Distribution-matching catches a subtler one -- a
mechanism noised on the wrong scale -- which is worth having and is not worth a
day of a five-day sprint.

---

## 6. Cards to mark `privacy-critical`

Red. A defect here does not merely produce a wrong number — it voids the
guarantee the product exists to provide.

```
S1-4   duplicate submissions      breaks the sensitivity bound
S2-3   budget refusal             unbounded disclosure
S2-4   append-only ledger         no audit trail
S2-6   contributor threshold      small-cell exposure
S2-9   concurrency test           double-spend under load
S2-12  remove per-contributor list  direct disclosure
```

---

## 7. Keeping it credible

- Move cards **when the work happens**, not in a catch-up session. Trello stamps
  every move, and a board built retroactively is visibly built retroactively.
- One card per sprint-planning and sprint-review event, so the agile process is
  evidenced rather than asserted.
- If a card is abandoned, move it to Done with a comment saying why it was
  dropped. Silent deletion looks like a board tidied for marking.
