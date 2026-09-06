# Sprint 2 — Review & Retrospective

**Bússola** · Quantic MSSE Capstone · Jorge Luis dos Santos Mendes
Solo project · Sprint 2 of 3 · Closed

---

## 1. Sprint goal — met

> Every published statistic is differentially private, every epsilon spend is
> recorded in an append-only ledger, and no release can exceed its
> collaboration's budget for the period.

Met. Live at <https://bussola-hub.onrender.com>.

**The sprint was one week, not four.** The plan in [REVIEW.md](REVIEW.md) §F
assumed four. Roughly 75% of it was cut — explicitly, at planning, before any
code — rather than attempted and abandoned. What was cut and why is §5 below.

The goal survived the compression because the cut fell on breadth, not on the
guarantee: one statistic type shipped instead of six, and the accounting,
concurrency safety and audit trail behind it were not reduced at all.

## 2. Delivered

| # | Story | Evidence |
|---|---|---|
| S2-1 | Benchmarks protected by differential privacy | Exponential mechanism over a public candidate grid; `privacy/mechanisms/` |
| S2-2 | Set a period's epsilon budget | `budget.BudgetPeriod`, admin console |
| S2-3 | Refuse releases exceeding the budget | `BudgetExhausted`; demonstrated live on the sixth cell of six |
| S2-4 | Append-only epsilon ledger | `budget.LedgerEntry`; `save()`, `delete()` and the QuerySet bulk paths all closed |
| S2-6 | Suppress cells below the threshold | Checked *before* any budget is touched |
| S2-7 | Budget split across statistics | Even split, rounding **up** so the charge is never less than the spend |
| S2-8 | Bounds rationale beside each benchmark | Rendered with the metric's declared range |
| S2-9 | Concurrency test | K parallel releases on real threads against real Postgres |
| S2-10 | Property-based budget invariant | 6 properties, incl. two boundary-targeted |
| S2-12 | Remove the per-contributor value list | **And a second leak found doing it** — see §4 |
| S2-13 | Local Postgres path + CI no-skip guard | `test_postgres_guard.py` |
| S2-14 | Mechanism registry | Strategy + Registry, selected from the catalog |
| S2-16 | Release + ledger in one transaction | `LedgerEntry.release` is NOT NULL |
| S2-17 | The invariant asserted in both directions | `benchmarks/test_releases.py` |
| S2-18 | Demo consortium resized to 50/50/6 | Deliberately uneven; see §7 |
| S2-20 | Bootstrap a hub with no shell access | Render's free tier has no shell |
| S3-7 | **Deploy to Render** | Sprint 1's only slipped goal, closed on day 1 |

**Carried to Sprint 3:** `S2-5` (accuracy intervals), `S3-9` (calibration
depth), `S2-19` (Sprint 2 demo recording, deliberately deferred).

## 3. Quality

- **280 tests** on Postgres (144 at end of Sprint 1); 274 passing plus 6
  correctly skipped on SQLite
- **83% coverage** (89% in Sprint 1 — the fall is real and explained in §5)
- `ruff` clean; migrations current; `check --deploy` clean
- CI green on Postgres with **zero skips**, enforced rather than hoped for

New test categories: concurrency, property-based, mechanism/statistical,
release-invariant, immutability, and an environment guard that fails the build
when tests that must run are skipped instead.

## 4. What went well

**Building the ledger before touching OpenDP.** Retro action A1, and it paid
twice over: the accountant, its concurrency test and its property tests all
landed with no OpenDP import anywhere in the tree. Had the library fought us in
week 2 there would still have been a working, auditable budget system. It also
meant the hardest correctness problem was solved while nothing else was moving.

**Planting the defect each test guards.** This is the practice worth carrying
into any future project. Six defects were planted deliberately; four were
caught immediately, and the two that were *not* were the valuable ones:

| Planted | Result |
|---|---|
| Remove `select_for_update()` | Caught — `ledger sums to 0.900000 against a budget of 0.7000` |
| Write the ledger entry *before* the budget check | **Passed** — the refusal test relies on rollback, not statement order |
| Accept `remaining × 1.0001` | **Passed** — property testing never lands on the boundary |
| Return the true quantile from the mechanism | Caught by 5 tests, *after* a worthless test was replaced |

**Two tests were not testing what their names claimed, and planting found
both.** The second row above meant transaction rollback was load-bearing and
untested; it now has its own tests. The third produced two boundary-targeted
properties.

**Distrusting a passing DP test.** The original mechanism test compared a
released quantile against the exact one and asserted they differed. It proved
nothing: the exponential mechanism selects from a 200-point grid while the
exact quantile interpolates between observed values, so the two differ *even
with no noise at all*. It would have passed against a mechanism providing zero
privacy. Replaced with tests that check randomness as randomness.

**Deploying on day 1.** Retro action A5. It surfaced three problems — no shell
for `createsuperuser`, tokens landing in a retained deploy log, and
`create_superuser()` bypassing password validators — while there was still a
week to fix them.

## 5. What went badly

**A privacy-critical function shipped without the tenancy check every other
part of the codebase has.** `spend()` took `budget_period`, `cohort` and
`metric` as independent arguments and verified nothing about them agreeing, so
a release could charge one collaboration's budget for another's cohort.
`compute_exact_benchmark` refuses that. `Submission.clean()` has it as RULE 3.
The function labelled privacy-critical was the one that omitted it.

It was found by **automated review, not by me, and not by my tests** — and my
tests actively hid it: `test_budgets_of_separate_collaborations_are_independent`
asserts two budgets do not affect each other, which passes cheerfully while a
cross-tenant spend is being written. *Independent* and *mismatch refused* are
different claims and I only tested the weaker one.

**Coverage fell from 89% to 83%.** Not a mystery: three management commands
(`release_period`, `load_submissions`, `bootstrap_deploy`) carry substantial
branching that is exercised end-to-end by hand and in the container, but only
partially by unit tests. Honest reading — the operational surface grew faster
than its tests. `release_period` in particular deserves tests it does not have.

**Three self-inflicted process failures, each costing real time:**

1. **Stale `__pycache__` twice.** A restored file kept testing as its planted
   version, so a correct fix looked broken. Root cause the second time was a
   test doing `sys.path.insert` then `import generate`, which caches the module
   under a name later imports reuse. Fixed properly by loading the file by path.
2. **Checked an exit code through a pipe** — `docker build ... | tail` reported
   `EXIT=0` for a build that had failed. This is *literally* retro action A3
   from Sprint 1, committed to writing, and I did it anyway within a day.
3. **Corrupted a template by splicing it with string replacement** until it had
   two `<body>` tags. Recovered by rewriting the file whole. Editing structured
   markup by index arithmetic is a false economy.

**Django's `{# #}` is single-line only.** A multi-line comment rendered as
literal text into the page — including the word the test asserted was gone,
which is how it was caught.

**What was cut, and why:**

| Cut | Reason |
|---|---|
| Count, mean, stddev mechanisms | Far worse value per epsilon (SPEC §6.1). At ε=1 split three ways a DP mean's interval came back **wider than the sum being estimated** |
| Accuracy intervals (`S2-5`) | `summarize()` returns none for the exponential mechanism. Needs simulation |
| 10 000-trial calibration (`S3-9`) | ~450 ms per release, and context reuse measured at **1.0× speedup** — the cost is the release itself. Needs its own CI job |
| zCDP accountant | Basic composition can be checked with a calculator and explained on camera |

Shipping only the statistic that works is a position, not a gap — but it is a
narrower product than the plan described, and the demo should say so.

**The suite went from ~9s to ~3m15s** (9m26s on CI). The mechanism tests run
OpenDP ~155 times. Deliberate, measured, and accepted rather than trimmed.

## 6. Actions for Sprint 3

| # | Action | From |
|---|---|---|
| B1 | When a test asserts two things are *independent*, add the test that asserts the mismatch is **refused**. The weaker claim passes while the bug is present. | The tenancy miss |
| B2 | Write tests for `release_period` and `load_submissions`. The operational surface outgrew its coverage. | 89% → 83% |
| B3 | Treat a test that has never been observed failing as **not yet written**. Plant the defect. | Four tests improved by planting; two were worthless |
| B4 | Never read `$?` through a pipe. Redirect to a file and check the status directly. | A3 repeated, one sprint later |
| B5 | Edit structured markup by rewriting whole files, not by index splicing. | The corrupted template |
| B6 | Record the Sprint 2 demo **before** Sprint 3 features. It is now the second recording owed, and the final video is an edit of three, not a performance. | S2-19 deferred |

## 7. The number that shapes Sprint 3

The Sprint 1 review closed on a table predicting that DP quartiles need roughly
50 contributors at ε = 1. Sprint 2 ran the real release path against a 106-
contributor consortium and got this, from the deployed hub:

| Cohort | N | q25 | median | q75 | |
|---|---|---|---|---|---|
| `2011` | 50 | 3048.0 | 3718.9 | 4175.1 | usable |
| `2320` | 47 | 3155.4 | 3370.1 | 4309.2 | usable |
| `2farm` | 6 | **158.5** | 190.9 | **73.4** | **q75 below q25** |

**At N = 6 the released third quartile came out below the first.** Each
quantile is drawn independently, so at small N the noise exceeds the spacing
between them and the ordering inverts. It reproduced across three separate
seeds, so it is a property of the mechanism at that scale, not a fluke.

The prediction became an observation, and the observation became a product
feature: `BenchmarkRelease.quantiles_are_ordered` detects it without touching
the data, and the dashboard says the release is too noisy to use.

It is deliberately **not** fixed by sorting. Sorting would be privacy-safe —
differential privacy is closed under post-processing — but it would conceal the
one signal telling a member not to trust the release, replacing a visibly
broken number with an invisibly meaningless one.

That is the sprint's strongest single result, and it came from running the
system rather than reasoning about it — which is the same lesson Sprint 1
closed on, arriving from the opposite direction.
