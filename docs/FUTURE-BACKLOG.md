# Future backlog — and the fork in the road

Written at the close of Sprint 3, when the sweep had just made the product's
limit measurable rather than suspected.

**The finding that forces this document:** ε·N ≈ 200. Quartiles worth publishing
need roughly 200 contributors at ε=1, 100 at ε=2, 50 at ε=4. Below N≈25 the
release stops being noisy and starts being *empty* — at N=5 it collapses every
contributor into one quartile 93% of the time.

That is not an implementation weakness to optimise away. It is the shape of the
guarantee. So the question this backlog answers is the one that follows:

> **What does a two-company, or five-company, or one-company deployment need
> instead?**

---

# Part 1 — Why small N breaks, and the three ways out

## The mechanism, stated plainly

Differential privacy calibrates noise to **sensitivity**: how much the answer
could move if one contributor were removed. Bússola's privacy unit is the
*contributor* (`MetricDefinition.contributions_per_period`, currently 1). With
five contributors, any one of them is 20% of the answer, so the noise required
to hide them is roughly the size of the signal.

There is no cleverer mechanism that escapes this. It is the definition doing its
job. Anyone who claims otherwise has quietly changed the privacy unit, weakened
the guarantee, or is measuring something else.

## The three escapes, and what each actually buys

| Route | What changes | Works at | Honest limit |
|---|---|---|---|
| **A. Change the privacy unit** | Protect *records*, not companies | N = 1 company | Only protects individuals inside the company, not the company itself |
| **B. Protect inputs, not outputs** | MPC, secure aggregation, TEEs | N = 2–10 | The **output still leaks**; see below |
| **C. Stop publishing statistics** | Governed access, audit, synthetic data | N = 1–5 | Sells governance, not a mathematical guarantee |

## The trap in route B, which the market glosses over

Secure aggregation and confidential computing protect data **in transit and in
computation**. Three companies can compute an exact mean without any of them
seeing another's input. The protocol is sound.

But the **published result is exact**, and an exact aggregate over a small group
is itself a disclosure:

- with **N = 2**, each party subtracts its own value and has the other's
  exactly;
- with **N = 3**, each party learns the exact mean of the other two;
- with any N, a coalition of N−1 reconstructs the last one perfectly.

So "we use MPC, therefore we do not need differential privacy" is selling a gap.
MPC removes the trusted curator; it does not remove the disclosure in the answer.
**The correct small-N architecture is input privacy *and* an output rule** —
either DP noise on the aggregate, or a suppression threshold, or both.

That is worth stating loudly because it is the single most common confusion in
this space, and Bússola is unusually well placed to demonstrate it: the sweep
harness can measure exactly what a secure-aggregation-plus-small-noise release
costs in utility, on the same data, against the same ground truth.

---

# Part 2 — The backlog

`F-` numbers to keep them distinct from the delivered `S-` cards. Effort is in
solo days. **Research** items produce a finding and a decision; **product**
items produce a feature.

## Theme A — Change the privacy unit (single company)

> **The cheapest real pivot in this document.** The codebase already models the
> privacy unit as a catalogue field. Most of this theme is configuration and
> framing rather than new machinery.

### F-1 · Record-level privacy unit · product · 3–5 days
**As** a single company with 12 plants, **I want** benchmarks across my own
sites, **so that** I can find the underperformers without exposing individual
plant managers' numbers to each other.

The reframe: when the deployment is one company, the thing being protected stops
being *which company contributed* and becomes *which plant, shift, batch or
employee*. A single company has thousands of records where it had one
contributor — and **DP works perfectly well at N = 3,000 records.**

`contributions_per_period` already carries this. The work is: let a contributor
submit multiple rows per period, make the privacy unit explicit in the admin,
and re-run the sweep with the record as the unit to get the honest curve.

*Unlocks:* a deployable product for a single mid-sized industrial group, which
is a far shorter sales cycle than a 50-member consortium.

### F-2 · Site-level cohorts within one tenant · product · 2 days
Cohorts currently model sectors across companies. The same structure models
plants within a company. Mostly naming, seed data, and a worked example.

### F-3 · Per-analyst epsilon budgets · product · 4 days
Budget scoped to the *querier*, not only the reporting period — the Trusted
Research Environment pattern. An analyst gets a personal allowance; the ledger
already records who spent what, once "who" becomes a column.

*Note:* this is the pattern already built freelance with PySyft for the
UNDP/IBGE work. Reusable thinking, not a cold start.

### F-4 · Re-run the sweep with the record as the privacy unit · research · 2 days
The whole point of building the harness against the shipped code is that this is
now a parameter change plus compute. Produces the F-1 equivalent of ε·N ≈ 200
and tells a single-company buyer what they will actually get.

---

## Theme B — Protect inputs instead of outputs (2–10 companies)

> **This is where a second product lives.** Different buyer, different
> technology, different failure modes.

### F-5 · Secure aggregation spike · research · 5 days
Additive masking with pairwise seeds — the SecAgg construction from federated
learning, which is far simpler than general MPC and sufficient for sums and
counts. Each contributor adds a mask that cancels when all masks are summed; the
hub sees only the total.

Deliverables: a working three-party sum with no trusted curator, a measurement
of what it costs in latency and coordination, and a written answer to *what
happens when a party drops out mid-round* — which is the practical failure mode
that kills naive implementations.

**Decision this spike makes:** whether Bússola can offer a no-trusted-curator
mode, or whether that is a separate product with a separate architecture.

### F-6 · Secure aggregation + calibrated noise · research · 3 days
The honest small-N architecture from Part 1. Aggregate securely, then add DP
noise sized for the *coalition* threat model rather than the curator one.

Measure it with the existing sweep harness against the same ground truth. This
is the experiment that produces a publishable comparison, and it is the natural
successor to the ε·N result.

### F-7 · Confidential computing spike (TEE) · research · 5 days
AWS Nitro Enclaves or equivalent. Data enters encrypted, the enclave attests to
the code it is running, only the aggregate leaves. This is what AWS Clean Rooms
and Decentriq actually do, so a spike here is also competitive research.

The interesting question is **attestation as a product feature**: can a
contributor verify, cryptographically, which version of the aggregation code
touched their data? That is a stronger claim than Bússola's current one, and it
is the thing an enterprise compliance officer will ask for.

*Caveat to test honestly:* TEEs move trust from an operator to a silicon vendor.
That is a real reduction, not an elimination, and the write-up should say so.

### F-8 · Private set intersection · research · 4 days
The most common genuinely two-party industrial question is not "how do I
compare" but **"do we share suppliers / customers / incidents, and how many?"**
PSI answers it while revealing only the intersection size.

Different question, different mechanism, possibly the easiest *first* product
for a two-company pilot because the value is obvious in one sentence.

### F-9 · Threat model document · research · 2 days
Written before any of B is built, not after. Who is the adversary in a
three-company consortium: the operator, a member, a coalition, an outsider with
the published output? Bússola's current answer assumes a trusted curator
(ADR-0002); every item in this theme changes that assumption, and changing it
implicitly is how these systems get broken.

---

## Theme C — The governance product ("a private app")

> The reading where the buyer wants **control and evidence**, not a
> mathematical guarantee. Often the actual purchase, especially under LGPD.

### F-10 · Generalise the epsilon ledger into a disclosure ledger · product · 4 days
Every query, who ran it, under what purpose, what left the building. Epsilon
becomes one column among several rather than the only thing recorded.

The append-only machinery, the immutability guards, the CSV export and the
reconciliation check are all built and tested. This is a widening, not a rebuild
— and it is what makes the system saleable to a buyer who does not care about
differential privacy at all.

### F-11 · Purpose limitation and LGPD artifacts · product · 5 days
Declared purpose per metric and per query; a generated record of processing
activities; the inputs a DPIA needs. Brazil-specific and directly aligned with
FIEB's institutional role.

### F-12 · Human approval gate before release · product · 3 days
A release proposal that a named person approves, with the approval in the
ledger. For a two-company arrangement, the review *is* the control — and it is
what a contract negotiation will demand anyway.

### F-13 · DP synthetic data export · research · 6 days
Instead of publishing statistics, publish a synthetic dataset carrying the
distribution. Buyer gets a file they can analyse freely; the guarantee is on the
generator.

For one company with many records this is viable and genuinely useful. **Do not
attempt it for a five-company consortium** — synthetic data over five records
per stratum is the collapse problem again, wearing a better outfit.

---

## Theme D — Utility of what already exists

### F-14 · zCDP or Rényi accountant · product · 4 days
Deliberately deferred twice, for a good reason: basic composition can be checked
with a calculator. But it is the single largest free win available — tighter
composition means materially more releases for the same ε, which moves the
ε·N ≈ 200 contour directly. `BudgetPeriod.accountant` already carries the choice
and refuses loudly rather than mis-accounting.

**Highest utility-per-day item in this document for the existing product.**

### F-15 · Smooth sensitivity / propose-test-release · research · 6 days
Data-dependent mechanisms that can beat the worst-case bound when the data is
well behaved. Real gains at moderate N; genuinely easy to get wrong. Only worth
it after F-14, and only with the sweep harness measuring it.

### F-16 · Trends across periods, done properly · product · 5 days
The `S3-6` card cut in Sprint 3. Cut because a line through independently-noised
releases is a plausible picture with no evidence behind it. Doing it properly
means budgeting the noise *across* periods so the trend is a first-class release
with its own accuracy statement — not five releases plotted together.

### F-17 · Weighted budget allocation · product · 2 days
Even split rounds up across statistics today. Members care more about the
median than about q25; letting an operator weight the split buys accuracy where
it matters for free.

---

## Theme E — Research that produces papers, not features

### F-18 · The local-DP crossover · research · 3 days
SPEC §8's secondary result, still unrun: repeat the sweep with noise applied at
the agent rather than the hub, and report the N at which local DP becomes
viable. Turns ADR-0002 from an argument into a measurement.

Cheap, because the harness exists.

### F-19 · Small-N comparison study · research · 8 days
**The paper that follows from this sprint.** Same synthetic cohorts, same ground
truth, same harness, four architectures:

1. central DP (built),
2. local DP (F-18),
3. secure aggregation + calibrated noise (F-6),
4. exact aggregation with a suppression threshold only.

Report utility and disclosure risk for each at N = 2, 3, 5, 10, 25. Nobody has
published this comparison for the small-consortium regime with an industrial
worked example, and the ε·N result is the natural setup for it.

### F-20 · Chinese-language privacy-computing survey · research · 4 days
China's 隐私计算 (privacy-computing) industry is commercially ahead of the
Western literature on exactly this problem — small-consortium data collaboration
— and its work is largely uncited in Brazilian I4.0 writing. A reading-ability
advantage most authors in this field do not have.

---

# Part 3 — Where the product forks

## What stays Bússola

Themes **A** and **D**, and **F-10** from C. Same thesis (the guarantee is
checkable rather than promised), same architecture, same trusted-curator model,
same code. A single-company or large-consortium deployment.

The honest positioning after the sweep: *Bússola is for groups of 25 or more, or
for one organisation benchmarking across its own sites.*

## What is a different product

Theme **B**, plus **F-11** to **F-13**. The tell is that all three assumptions
change at once:

| | Bússola | The second product |
|---|---|---|
| Trust model | trusted curator | no trusted curator |
| Privacy comes from | noise on the output | protocol on the inputs |
| Buyer | a federation or association | a company, or a pair of them |
| Sold on | a published guarantee | control, attestation, and audit |
| Typical N | 25–200 | 2–10 |

Different technology, different buyer, different sentence on the front page.
Sharing a codebase between them would mean two trust models in one system, which
is how privacy products acquire quiet holes.

**The fork is real, and it is worth being explicit that it is a fork.**

## Recommended order, if this continues

1. **F-14** (zCDP). Best utility per day for what exists, and it moves the
   headline number the article is built on.
2. **F-1 + F-4** (record-level privacy unit, and re-measure). Makes the current
   product deployable for a single company — the shortest path to a real pilot,
   and it reuses everything.
3. **F-9 then F-5** (threat model, then secure aggregation). The threat model
   first, deliberately. Building input privacy without writing down the
   adversary is how the coalition case in Part 1 gets missed.
4. **F-19** (the comparison study). By this point three of its four arms exist.

Items 1 and 2 keep Bússola one product. Item 3 is where the second one starts,
and the threat model is the document that will say whether it should.

---

## One thing to carry across the fork

Whatever gets built next: **plant the defect the test claims to catch.**

Across Sprints 2 and 3 that practice found a privacy-critical tenancy hole, a
sweep measuring ten times the epsilon it charged, a mechanism test that would
have passed against no privacy at all, and two tests asserting the right string
against the wrong scenario. Every one of them passed CI first.

Cryptographic protocols fail more quietly than Django views do. A secure
aggregation implementation with a subtly wrong mask cancels to the right answer
and protects nothing, and no unit test notices, because the output is correct.
