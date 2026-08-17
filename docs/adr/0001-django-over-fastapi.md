# ADR-0001 — Django over FastAPI

**Status:** Accepted · Sprint 1

## Context

The hub needs an HTTP API for agents, an operator console, a member-facing
dashboard, and — from Sprint 2 — a privacy budget ledger. FastAPI is the
reflexive modern choice for a Python API service, so the alternative deserves an
explicit justification.

## Decision

**Django 5 + Django REST Framework.**

## Consequences

### Reasons for

1. **The epsilon ledger is a transactional relational problem.** Two concurrent
   releases must not double-spend the privacy budget. The fix is
   `select_for_update()` inside `transaction.atomic()`, and Django's ORM makes
   that critical section three lines. Getting this wrong voids the guarantee the
   product exists to provide, so the framework that makes it easiest wins.

2. **Django admin is the operator console, for free.** The Consortium Analyst
   manages metrics, periods and tokens; the Auditor inspects the ledger. Both
   are served by admin with customisation rather than bespoke CRUD. Working
   solo, this is roughly two weeks not spent on forms — which is why no admin UI
   appears anywhere in the backlog.

3. **Migrations.** The privacy schema will change repeatedly across three
   sprints. Alembic is fine but is one more thing to wire up.

4. **Templates mean one deployable.** A React SPA or a Streamlit dashboard would
   mean two build pipelines and two free-tier services, for no rubric benefit.

### Reasons against, acknowledged

FastAPI offers async I/O, native pydantic validation, and automatic OpenAPI.
None is on the critical path: submission volume is a handful of requests per
plant per month, and the shared `bussola-contracts` package already gives
pydantic validation on the agent side. Ledger integrity matters more than
request throughput.

### Cost paid

DRF serializers duplicate what pydantic already expresses in
`bussola-contracts`. That duplication is mitigated — not eliminated — by the
contract test, which asserts the two field sets match in both directions.
