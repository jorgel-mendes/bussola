# Sprint 3 — Review & Retrospective

**Bússola** · Quantic MSSE Capstone · Jorge Luis dos Santos Mendes
Solo project · Sprint 3 of 3

> **Written before the final recording (`S3-8`), which is the one deliverable
> still outstanding.** Everything else in this document is closed. Recording it
> after writing the review is deliberate — the review is what the recording is
> narrated from, not a summary written afterwards to match it.

---

## 1. Sprint goal — met

> Turn the guarantee into evidence. A member should be able to see where they
> stand and how much to trust it; an auditor should be able to check the budget
> without taking anyone's word for it; and the privacy–utility trade-off should
> be measured rather than argued.

Met, and the measurement went further than the plan expected — it overturned the
demo's headline sentence. Live at <https://bussola-hub.onrender.com>.

**Two weeks of plan into one week again**, and again by cutting at planning
rather than abandoning mid-sprint. What was cut is §5.

## 2. Delivered

| # | Story | Evidence |
|---|---|---|
| S3-3 | The privacy–utility sweep | `evaluation/sweep.py`; 7,000 releases, 2h47m; [RESULTS.md](../evaluation/RESULTS.md) |
| S3-3 | The curve in the dashboard | Correct-quartile rate vs ε, one line per cohort size |
| S3-3 | A reading for *this* release | "at ε=1 with 50 contributors, 66.9% land correctly" |
| S3-2 / S2-5 | Accuracy intervals | By simulation, inverted and clamped — §4 |
| S3-1 | Contributor position view | `bussola-agent position`, token-authenticated, spends nothing |
| S3-4 | Ledger CSV export | Running cumulative epsilon; admin action + management command |
| S3-5 | Dry-run in the operator guide | Folded into the README, which needed rewriting anyway |
| S3-10 | Retired vocabulary in the product | The agent's `--help` still said "plant" |
| S2-19 | Sprint 2 demo recorded | Carried from Sprint 2, closed on day 1 |
| B2 | `release_period` / `load_submissions` tests | Retro action; both were at **0%**, now 97% |
| — | README rewritten | It still opened with Sprint 1's "exact, unprotected statistics" banner |

**Cut, deliberately:** `S3-6` (trend across periods), `S3-9` (10,000-trial
calibration depth).

## 3. Quality

- **408 tests** (280 at Sprint 2 close), **93% coverage** (83%)
- `ruff` clean; migrations current; `check --deploy` clean
- CI green on Postgres with zero skips
- The sweep runs in its own workflow — the main suite would otherwise sit behind
  two and a half hours

New test categories: cross-implementation agreement (the loader's value asserted
against the *agent's own function*, not against a number typed into the test),
rendered-output vocabulary, and simulation-backed display bounds.

## 4. What went well

**Building the sweep on day 1 and letting it run.** It is the long pole — 2h47m
— and everything else in the sprint reads it: the intervals, the curve, the
per-release guidance, and the article. Starting it before the UI work meant the
compute and the human work never competed. Retro action A1 and A5 in a new
costume: do the thing everything depends on first.

**Refactoring so the harness calls the shipped code.** `build_context`,
`per_statistic_epsilon`, `quartile_of` and `quantiles_ordered` were all extracted
so the sweep runs the product rather than a copy of it. That was the sprint's
best decision, and the reason is §5's first entry.

**Planting kept earning its keep — 17 defects planted across the sprint.**
Fourteen were caught. Two passed and should not have, and both are in §5. The
seventeenth passed correctly: wrapping the release loop in an outer transaction
is a genuine no-op, because the loop catches its own exception and breaks, so
nothing propagates. That one is recorded because the expectation was mine and it
was wrong — the plant was not a missed defect, it was a defect I had invented.

**Looking at the rendered page, not just the tests.** Two defects that no test
would have caught: a panel that rendered white-on-white in dark mode, and a band
that printed 12,996 MJ/t against a declared ceiling of 7,100. The second is a
correctness bug — it asserted a value the model excludes — and it was found by
printing the numbers the page would show.

**Refusing to tune the demo.** The sweep says ε=1 at N=50 places 66.9% of
contributors correctly. Raising ε until that number looked good was available
and was not taken: ε=1 is what the literature uses, so it is the number a reader
can compare against, and the gap is the future work stated with a figure
attached. Showing a benchmark while knowing a third of members are misplaced is
the failure this project argues against; showing it *and saying so* is the
thesis applied to itself.

## 5. What went badly

**Four findings, one shape: a green build with something missing.** This is the
sprint's real lesson, and it took four instances before I saw the pattern.

| Found | What was absent | What was green |
|---|---|---|
| Sweep ran at 10× the epsilon it charged | the link between noise and price | all 21 harness tests |
| `.gitignore` had unanchored `data/` | the digest, from the deployed image | 363 tests, and the page still rendered |
| Stacked PR merged into its own base | `S3-2`, from `main` | the PR said MERGED; CI stayed green |
| B2 test used a budget of 1.2 | the scenario the test was named for | the test itself |

Every one is an **absence**, and no test catches an absence it does not know to
look for. How each surfaced is worth recording, because only half came from the
practice designed to find them:

- the sweep's epsilon and the B2 budget: **planting**, which is what it is for;
- the `.gitignore` rule: a `git check-ignore` run on a hunch, after noticing the
  digest missing from a `git status` I had no particular reason to read;
- the stranded pull request: **I asked whether it had actually gone to `main`.**
  Nothing in the tooling would have said otherwise — the PR reported MERGED and
  `main` stayed green.

The last one is the uncomfortable entry. The only thing standing between that
work and silent loss was being suspicious of a green result.

The first is the most serious. The sweep produces the article's numbers, and
multiplying its context epsilon by ten — measuring a privacy level ten times
more generous than the hub actually spends — left every test passing. The suite
asserted that a release is noisy, and that the charge splits correctly, and
never that the noise and the charge refer to the *same* epsilon. That is retro
action B1 from Sprint 2 arriving from a new direction: I had tested the
components and not the relationship between them.

**A flaky test took `main` red, and it was mine.** The accuracy-interval test
asserted which display branch rendered, against a fixture that runs a real DP
release and therefore picks the branch at random — 2 failures in 6 runs. It
passed on my machine and on its own pull request, and failed only after merging.

The uncomfortable part is not the bug. It is that **a passing run of a
randomised test is one sample, and I treated it as a pass** — the same mistake
as B3 ("a test never observed failing is not yet written"), one level up. A CI
gate does not fix this, because the gate is also one sample.

**The SPEC's predicted headline was wrong by a factor of two.** §8 set the demo
sentence at "at ε=1.0 with 25 plants, 96% of plants are assigned to the correct
quartile". Measured: **47.6%**. It was a guess written before anything had been
run, which is what the sweep was for — but it had been sitting in the plan as a
target since Sprint 1, and nothing had challenged it.

**I stacked a pull request and lost a day's work off `main`.** #10 was based on
#9 because it needed its code. GitHub retargets a stacked PR only when its base
branch is deleted on merge; the base survived, #9 merged first, and #10 merged
into a branch that had already been merged away. Recovered in full, but the
correct call was to wait rather than to stack.

## 6. The number that shapes the article

Three cells of the grid clear 90% correct with no unusable release in 200 trials:

| ε | N | ε·N | correct | unusable |
|---|---|---|---|---|
| 8.0 | 25 | 200 | 91.7% | 0.0% |
| 4.0 | 50 | 200 | 94.0% | 0.0% |
| 2.0 | 100 | 200 | 94.4% | 0.0% |

**ε·N ≈ 200. To halve the privacy cost, double the cohort.** It also prices the
guarantee: a consortium wanting ε ≤ 1 needs roughly 200 contributors. Bahia has
106.

And the counterweight, which matters more for the honesty of the result:
**epsilon cannot buy its way out of a small cohort.** At N=5 the correct-quartile
rate moves from 36.8% at ε=0.1 to only 50.8% at ε=8 — a privacy level OpenDP
itself warns about. Worse, the metric flatters it: at N=5 and ε=0.1 all three
true quartile points fall in a *single* noisy bucket 93% of the time, and the
released IQR is 2,791 MJ/t against a true 427. A 37% correct-quartile rate there
is the score you get free by putting everyone in one bucket, because 2 of 5
genuinely belong there.

That is why the unusable-release rate is reported beside the headline and not
behind it. At N=5, ε=0.1 it reads 82%, and 82% is the truth.

**Independent corroboration.** The Sprint 2 demo preparation separately measured
the N=6 out-of-order beat firing 73% of the time over 120 trials. The sweep, on
synthetic cohorts through a different code path, gives 74.5% unusable at N=5,
ε=1.0. The Sprint 2 observation was not a fluke of one seeded dataset.

## 7. Actions

Carried out of the project rather than into a next sprint, since there is not
one.

| # | Action | From |
|---|---|---|
| C1 | Test the RELATIONSHIP between components, not only each component. The ε×10 defect passed because noise and price were each tested alone. | The sweep |
| C2 | A passing run of a randomised test is one sample. Run it repeatedly, or fix the seed, before trusting it — a CI gate is also one sample. | The flaky test |
| C3 | Ask what would be *absent* if this were wrong, not only what would break. Four findings this sprint were absences behind a green build. | §5 |
| C4 | Read the rendered output, not only the assertions about it. Two real defects, including one correctness bug, were visible only on the page. | Dark mode; the 12,996 band |
| C5 | Do not stack pull requests. Wait for the base to merge, or merge the child first. | #10 |
| C6 | When a guard misses something, ask what it *cannot* see. The naming-drift test strips string literals by design, so user-facing prose was never in its scope. | S3-10 |

## 8. Honest note on how this was built

Sprints 2 and 3 were built in pair with an AI assistant (Claude), used for
implementation, test design and review. The design decisions, the cuts, the
demo-parameter call and the interpretation of the sweep are mine; a substantial
share of the code and test drafting is not.

Recording it because the alternative is a claim I would not want examined, and
because two of this sprint's findings — the ε×10 plant and the tenancy miss in
Sprint 2 — were found by exactly that pairing. The practice that made it safe
is the one this project already had: **plant the defect the test claims to
catch.** An assistant will write a test that passes. Planting is what tells you
whether it was testing anything.
