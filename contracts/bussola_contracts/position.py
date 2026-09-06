"""Hub -> agent contract for a contributor's own position (S3-1).

The member's real question is not "what is the released median". It is
**"where am I?"** -- and answering it is the whole reason a plant agrees to
contribute at all.

Everything in this report is either the contributor's OWN data or an
already-published differentially private release. Nothing here is computed on
demand and nothing here costs privacy budget: placing a value you already own
against numbers that were already published is post-processing, and DP is closed
under post-processing.

The field names say `released_` out loud. These are noisy values drawn from the
exponential mechanism, not the cohort's true quartiles, and a contributor
reading `q75` would reasonably assume otherwise.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from bussola_contracts.submissions import CONTRACT_VERSION


class PositionReport(BaseModel):
    """Where one contributor sits against its cohort's published benchmark.

    `quartile` is "Q1".."Q4", or "unknown" when the release cannot support the
    comparison. `caveat` then says why, in a sentence meant for the member
    rather than for the operator.
    """

    model_config = ConfigDict(frozen=True)

    contract_version: str = CONTRACT_VERSION

    metric_code: str
    metric_unit: str
    period_label: str
    cohort_code: str

    #: The contributor's own submitted aggregate. Their data, returned to them.
    your_value: Decimal

    #: How many contributors the release covered, and what it cost. Both are
    #: already public on the dashboard; repeating them here means the agent can
    #: show the whole picture without a second call.
    n_contributors: int
    epsilon_spent: Decimal

    released_q25: Decimal
    released_median: Decimal
    released_q75: Decimal

    quartile: str
    is_usable: bool
    caveat: str | None = None
