"""Ledger export for the Auditor (S3-4).

The Auditor's question is not "what is in the ledger". It is **"was more
privacy spent than was authorised, at any point in the period?"** A flat dump of
rows does not answer that; it makes the auditor recompute it, in a spreadsheet,
by hand, which is exactly the sort of step that gets skipped.

So every row carries a **running cumulative epsilon** alongside its own spend.
Basic composition means epsilon adds linearly (`budget.models.Accountant`),
so the cumulative column IS the composition -- visible, checkable against
`budget_total` on the same row, and readable by anyone who can scroll a
spreadsheet. Making the accountant explicable was the reason basic composition
was shipped first; this is that decision paying out.

The rows are read-only by construction. Nothing here writes, and the ledger
could not be edited through it even if it tried (`LedgerEntry` is append-only,
RULE 1).

ORDER IS PART OF THE CONTENT. Entries are exported in ledger order -- the
model's own `created_at, id` -- because a cumulative total over rows in any
other order is a different number, and a plausible wrong one.
"""

from __future__ import annotations

import csv
from decimal import Decimal

#: Column order. Stable, because an auditor's spreadsheet or script will index
#: these; reordering them silently would break a downstream check that has no
#: way to notice.
COLUMNS = [
    "entry_id",
    "created_at",
    "collaboration",
    "period",
    "cohort",
    "metric",
    "statistic",
    "mechanism",
    "epsilon_spent",
    "cumulative_epsilon",
    "budget_total",
    "budget_exceeded",
    "release_id",
]


def ledger_rows(entries, budget_total: Decimal | None = None):
    """Yield one dict per ledger entry, in ledger order, with a running total.

    `entries` must already be ordered by (created_at, id) -- `LedgerEntry.Meta`
    does this by default. It is consumed exactly once, so a queryset is fine and
    a generator is fine.

    `budget_exceeded` is the column an auditor filters on: True on any row where
    the cumulative spend has passed the authorised total. It should never be
    True. If it ever is, that is the finding, and it should be visible without
    anyone having to compute anything.
    """
    cumulative = Decimal("0")
    for entry in entries:
        cumulative += entry.epsilon_spent
        total = budget_total if budget_total is not None else entry.budget_period.epsilon_total
        yield {
            "entry_id": entry.pk,
            "created_at": entry.created_at.isoformat(),
            "collaboration": entry.budget_period.period.collaboration.slug,
            "period": entry.budget_period.period.label,
            "cohort": entry.cohort.code,
            "metric": entry.metric.code,
            "statistic": entry.statistic,
            "mechanism": entry.mechanism,
            "epsilon_spent": entry.epsilon_spent,
            "cumulative_epsilon": cumulative,
            "budget_total": total,
            "budget_exceeded": cumulative > total,
            "release_id": entry.release_id,
        }


def write_ledger_csv(entries, fh, budget_total: Decimal | None = None) -> int:
    """Write the ledger to an open text file object. Returns the row count.

    The count is returned rather than discarded so the caller can reconcile:
    an export that silently dropped rows -- a stray slice, a filter, a
    paginator -- would hand an auditor an incomplete record that still looks
    complete, and they would sign it off. `export_ledger` and the admin action
    both check it against the ledger's own count.
    """
    writer = csv.DictWriter(fh, fieldnames=COLUMNS)
    writer.writeheader()
    written = 0
    for row in ledger_rows(entries, budget_total=budget_total):
        writer.writerow(row)
        written += 1
    return written


def export_filename(*, collaboration_slug: str, period_label: str) -> str:
    """A filename that says what the file is without being opened."""
    return f"bussola-ledger-{collaboration_slug}-{period_label}.csv"
