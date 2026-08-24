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

| Label | Colour | Use |
|---|---|---|
| `sprint-1` | green | |
| `sprint-2` | yellow | |
| `sprint-3` | blue | |
| `privacy-critical` | red | Cards where a defect voids the guarantee |
| `deliverable` | purple | Graded artifacts (docs, recordings, deployment) |

---

## 2. Two paste tricks

**Cards.** Click **+ Add a card**, paste a multi-line block, accept Trello's
offer to create one card per line.

**Checklist items.** Checklists live *inside* a card, not on the board. Open the
card → **Checklist** in the right sidebar (under the **Add** menu in newer
Trello) → name it → then paste all lines at once into the "Add an item" box.
Trello splits them into one item per line, exactly like cards.

---

## 3. Current board state

### Done (11) — Sprint 1 delivery

```
S1-1  Define a metric with bounds and a required rationale
S1-2  Register a contributor and issue an API token
S1-3  Run bussola-agent submit from a contributor machine
S1-4  Reject duplicate submissions (one value per contributor/period/metric)
S1-5  Open and close a reporting period
S1-6  Show an exact cohort benchmark behind an UNSAFE banner
S1-7  Get CI running on every push
S1-8  Generate synthetic multi-contributor data with ground truth
S1-9  Prove multi-party shape with docker-compose agents
S1-10 Write the design and testing document
S1-11 Write ADRs 0001-0003
```

### Move to Done now (work already complete)

| Card | Evidence |
|---|---|
| **S1-12** Create and publish the Trello board | Board live and verified public |
| **S1-14** Fix the CI badge URL in README | Real account wired in; badge renders |
| **S1-15** Verify the Docker builds | Both images build; compose demo runs; found 3 defects |

### Sprint Backlog — actually remaining (3)

```
S1-13 Push repo to GitHub and share with quantic-grader
S1-16 Spike OpenDP in a standalone notebook
S1-17 Record the Sprint 1 demo
```

### Product Backlog (20)

Sprint 2 and Sprint 3 cards, unchanged. Two of them (S2-12, S3-1) still use retired vocabulary — see §5.

---

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
