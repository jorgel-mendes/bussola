"""A contributor's position against its cohort's published release (S3-1).

WHY THIS COSTS NO PRIVACY BUDGET

Two inputs, and neither is a new disclosure:

1. the contributor's own submitted value -- their data, returned to them;
2. an already-published `BenchmarkRelease` -- differentially private, already
   charged to the ledger, already visible on the dashboard.

Placing (1) against (2) is post-processing, and differential privacy is closed
under post-processing. Nothing here runs a mechanism, and that is enforced
rather than intended: this module imports nothing from `privacy`, and a test
asserts that hitting the endpoint repeatedly writes no ledger entry and creates
no release. If answering "where am I?" released anything, an agent on a cron
would drain its collaboration's budget overnight.

WHEN THE ANSWER IS REFUSED

If the released quantiles are out of order -- which happens at small N, and was
observed on the deployed hub at N=6 -- there is no defensible quartile to
report. The rule is the same one the dashboard follows: say the release is
unusable rather than hand back a plausible number computed from a broken one.
Sorting the triple first would produce an answer, and it would be privacy-safe,
and it would be worse: the member would act on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from benchmarks.models import QUANTILE_STATISTICS, BenchmarkRelease
from benchmarks.selectors import quartile_of

UNKNOWN = "unknown"


class PositionUnavailable(Exception):
    """No position can be reported, and the reason is meant for the member.

    A distinct exception rather than a None return: every caller must decide
    what to tell the contributor, and a silent None invites a page that renders
    an empty quartile as though it were an answer.

    `code` exists so an agent can act without parsing prose -- the same
    principle as the 409/422 split on the submission endpoint. The three cases
    call for three different responses:

      not_submitted       the contributor's own problem; submit, then ask again
      not_published       the operator has not released yet; retry later
      incomplete_release  neither; the operator must look at it
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Position:
    """Where one contributor sits, and how much to trust it."""

    submission_value: Decimal
    release: BenchmarkRelease
    released: dict[str, Decimal]
    quartile: str
    is_usable: bool
    caveat: str | None = None


def position_for(*, contributor, metric, period) -> Position:
    """Place a contributor against its own cohort's published release.

    The cohort is taken from the contributor, never from the caller. A member
    cannot ask where it would sit in another cohort, which would let it probe a
    distribution it does not belong to.

    Raises PositionUnavailable when there is no submission or no release.
    """
    submission = _own_submission(contributor, metric, period)

    release = (
        BenchmarkRelease.objects.filter(
            cohort=contributor.cohort, metric=metric, period=period
        )
        .prefetch_related("statistics")
        .first()
    )
    if release is None:
        raise PositionUnavailable(
            f"Nothing has been published yet for cohort "
            f"'{contributor.cohort.code}' on '{metric.code}' in {period.label}. "
            f"Either the operator has not released this period, or the cohort had "
            f"too few contributors to publish without exposing them.",
            code="not_published",
        )

    released = {
        statistic.statistic: statistic.value
        for statistic in release.statistics.all()
        if statistic.statistic in QUANTILE_STATISTICS
    }
    missing = [s for s in QUANTILE_STATISTICS if s not in released]
    if missing:
        raise PositionUnavailable(
            f"The release for {period.label} does not include "
            f"{', '.join(missing)}, so a quartile cannot be reported.",
            code="incomplete_release",
        )

    # The usability rule the dashboard shows, applied to the same release.
    if not release.quantiles_are_ordered:
        return Position(
            submission_value=submission.value,
            release=release,
            released=released,
            quartile=UNKNOWN,
            is_usable=False,
            caveat=(
                "This release is too noisy to place you against. The published "
                "quartiles came back out of order, which happens when a cohort is "
                "small enough that the privacy noise exceeds the spacing between "
                "them. Your position is not reported rather than guessed."
            ),
        )

    return Position(
        submission_value=submission.value,
        release=release,
        released=released,
        quartile=quartile_of(
            submission.value, released["q25"], released["median"], released["q75"]
        ),
        is_usable=True,
        caveat=(
            "Quartile boundaries are differentially private releases, not exact "
            "values. A contributor sitting close to a boundary may be reported on "
            "either side of it."
        ),
    )


def _own_submission(contributor, metric, period):
    """The contributor's own aggregate, or a refusal that says what to do."""
    from ingest.models import Submission

    submission = Submission.objects.filter(
        contributor=contributor, metric=metric, period=period
    ).first()
    if submission is None:
        raise PositionUnavailable(
            f"You have not submitted '{metric.code}' for {period.label}, so there "
            f"is nothing to place against the benchmark.",
            code="not_submitted",
        )
    return submission
