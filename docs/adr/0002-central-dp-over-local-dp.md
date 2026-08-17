# ADR-0002 — Central differential privacy, not local

**Status:** Accepted · Sprint 1

## Context

Differential privacy can be applied at two points, and the choice determines the
whole system architecture:

- **Local DP** — each plant adds noise to its own value before transmitting.
  The hub never sees a true value and need not be trusted.
- **Central DP (trusted curator)** — plants transmit raw aggregates over an
  authenticated channel; the hub adds noise once, at publication.

The initial sketch for this project assumed local DP, on the intuition that
noising earlier is strictly safer.

## Decision

**Central DP with the association as trusted curator.**

## Consequences

### Why local DP fails here

Local DP error scales roughly √N worse than central DP for the same ε, because
every contributor's noise is independent and accumulates rather than cancelling.
Apple and Google deploy local DP successfully because they have on the order of
10⁸ contributors, which drowns the noise.

An industrial consortium has N ≈ 10–50 plants. At that scale local DP produces
benchmarks indistinguishable from noise — the system would be technically
private and practically useless, which is a failure, not a trade-off.

### Why the trusted curator is defensible

The US Census Bureau used the central model for the 2020 census — the largest
and highest-stakes DP deployment to date. More specifically to this project, an
industry federation *already is* the institutional trusted curator: holding
member data neutrally is what a federation is for. The model matches an existing
governance relationship rather than inventing one.

### Residual risk, accepted and stated

The hub operator sees raw submissions. Mitigations are organisational — access
control, admin action logging, an audit trail — not cryptographic. This is
recorded honestly in the design document rather than glossed.

Secure aggregation (pairwise masks that cancel in the sum, so the server learns
only the total) would remove this residual risk. It is future work, roughly
150 lines, and explicitly **not** claimed as delivered.

### Downstream effects

- The agent computes and transmits a plain aggregate; all DP machinery lives in
  the hub's `privacy` app. This makes the agent much simpler.
- A production deployment must run in the association's own tenant, since the
  operator is the trust boundary. That removes shared multi-tenant SaaS from the
  hosting options — a cost consequence flowing directly from a privacy decision.
- The comparison is measurable. Sprint 2's evaluation can re-run the sweep with
  agent-side noise and report the crossover N at which local DP becomes viable,
  turning this architectural assertion into a measured result.
