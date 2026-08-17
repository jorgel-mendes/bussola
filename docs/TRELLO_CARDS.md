# Trello board setup — paste-ready

The task board is a graded deliverable. It must be **Public** and it must show
work as it happens.

## 1. Board setup (5 minutes)

1. Free account at [trello.com](https://trello.com) — personal, no paid plan needed.
2. Create a board: **Bússola — MSSE Capstone**
3. **Board menu → Settings → Visibility → Public.**
   `quantic-grader` must open it without an invite. This is the step people miss.
4. Create five lists, left to right:

```
Product Backlog
Sprint Backlog
In Progress
Blocked
Done
```

5. Put the board URL in `README.md` (the deliverables table at the top).

### Labels

Create these five, they make the board readable at a glance:

| Label | Colour | Use |
|---|---|---|
| `sprint-1` | green | |
| `sprint-2` | yellow | |
| `sprint-3` | blue | |
| `privacy-critical` | red | Cards where a defect voids the guarantee |
| `deliverable` | purple | Graded artifacts (docs, recordings, deployment) |

---

## 2. The paste trick

In Trello, click **+ Add a card**, paste a multi-line block, and Trello offers
to create one card per line. Accept it. Do this once per list below.

---

## 3. Done — Sprint 1 (paste into **Done**)

These are genuinely complete and verified, so they belong in Done. Move each one
across yourself as you review the code, rather than all at once — the card
timestamps are part of what makes the board credible.

```
S1-1 Define a metric with bounds and a required rationale
S1-2 Register a plant and issue an API token
S1-3 Run bussola-agent submit from a plant machine
S1-4 Reject duplicate submissions (one value per plant/period/metric)
S1-5 Open and close a reporting period
S1-6 Show an exact sector benchmark behind an UNSAFE banner
S1-7 Get CI running on every push
S1-8 Generate synthetic multi-plant data with ground truth
S1-9 Prove multi-party shape with docker-compose agents
S1-10 Write the design and testing document
S1-11 Write ADRs 0001-0003
```

## 4. Sprint Backlog — remaining Sprint 1 (paste into **Sprint Backlog**)

```
S1-12 Create and publish the Trello board
S1-13 Push repo to GitHub and share with quantic-grader
S1-14 Fix the CI badge URL in README
S1-15 Verify the Docker builds once the daemon is running
S1-16 Spike OpenDP in a standalone notebook
S1-17 Record the Sprint 1 demo
```

`S1-16` is the one to protect — see the note in §6.

## 5. Product Backlog (paste into **Product Backlog**)

```
S2-1 Protect published benchmarks with differential privacy
S2-2 Set a reporting period's epsilon budget
S2-3 Refuse releases that would exceed the budget
S2-4 Record every epsilon spend in an append-only ledger
S2-5 Show an accuracy estimate before releasing
S2-6 Suppress cells with fewer than five contributors
S2-7 Split budget across the statistics in a release
S2-8 Show the bounds rationale next to each benchmark
S2-9 Write the concurrency test for budget double-spend
S2-10 Write property-based tests for the budget invariant
S2-11 Write statistical calibration tests for each mechanism
S2-12 Remove the per-plant value list from the dashboard
S3-1 Show a plant its position against the sector distribution
S3-2 Show confidence intervals on every published value
S3-3 Put the privacy-utility curve in the dashboard
S3-4 Export the epsilon ledger as CSV
S3-5 Add a dry-run mode note to the operator guide
S3-6 Compare a plant's trend across periods
S3-7 Deploy to Render and add the URL to README
S3-8 Record the final 15-20 minute demo
```

---

## 6. Checklists worth adding

Cards carry the user story; checklists carry the tasks. The handbook asks for
both. Don't do this for all 40 cards — only these three earn it.

**S1-16 Spike OpenDP in a standalone notebook** — `sprint-1`
This is the card that de-risks Sprint 2. ADR-0003 states the hypothesis; the
spike's job is to confirm or kill it while it is still off the critical path.
```
Install with: uv sync --extra dp
Build a Context over the submissions table
Confirm dp.unit_of(contributions=30) expresses plant-level privacy
Release a DP median using a candidate grid from the metric bounds
Call summarize(alpha=0.05) and record the accuracy interval
Compare noisy vs true quartiles at epsilon = 0.5, 1, 2
Decide: proceed with OpenDP, or fall back to diffprivlib
```

**S1-15 Verify the Docker builds** — `sprint-1`
```
Start Docker Desktop
docker build -f deploy/Dockerfile.hub .
docker build -f deploy/Dockerfile.agent .
docker compose up --build hub
docker compose run --rm seed
docker compose up agent-01 agent-02 agent-03
Confirm the dashboard shows three contributors
```

**S1-17 Record the Sprint 1 demo** — `sprint-1` `deliverable`
Record one per sprint even though Sprint 1 is local. Three short recordings make
the final 15–20 minute video an edit rather than a performance.
```
Show the metric catalog and the bounds rationale in admin
Issue a token, show it is displayed only once
Run bussola-agent submit --dry-run, then submit
Show idempotency: resubmit, count stays the same
Show a 401 with a revoked token
Show the dashboard, read the UNSAFE banner aloud
Show the suppression path on an empty period
Show CI green on GitHub
```

---

## 7. Cards to mark `privacy-critical`

Tag these red. They are the cards where a defect does not merely produce a wrong
number — it voids the guarantee the product exists to provide.

```
S1-4   duplicate submissions      breaks the sensitivity bound
S2-3   budget refusal             unbounded disclosure
S2-4   append-only ledger         no audit trail
S2-6   contributor threshold      small-cell exposure
S2-9   concurrency test           double-spend under load
S2-12  remove per-plant list      direct disclosure
```

---

## 8. Keeping it credible

- Move cards **when the work happens**, not in a catch-up session. Trello stamps
  every move, and a board built retroactively is visibly built retroactively.
- One card per sprint-planning and sprint-review event, so the agile process is
  evidenced rather than asserted.
- If a card is abandoned, move it to Done with a comment saying why it was
  dropped. Silent deletion looks like a board that was tidied for marking.

## 9. Alternative: GitHub Projects

The handbook says "typically a Trello Scrum Board **or other appropriate board**",
so GitHub Projects is permitted, lives beside the repo, and auto-links issues to
commits — arguably better evidence of work.

Trello is still the safer pick: the handbook names it explicitly, and its public
visibility toggle is one click with no ambiguity about whether a logged-out
grader can see it. Only switch if you would genuinely prefer working in
Projects.
