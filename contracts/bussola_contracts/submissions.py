"""Agent -> hub submission contract."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "1.0"

# Mirrors ingest.models.Submission field limits. The agent enforces these before
# the network call so an out-of-range value fails locally with a clear message
# rather than as an opaque 422.
MAX_DIGITS = 18
DECIMAL_PLACES = 6


class MetricSpec(BaseModel):
    """A metric definition as published by the hub's catalog endpoint.

    The agent fetches this to validate locally before submitting. ``lower_bound``
    and ``upper_bound`` are the DP clamping bounds -- they come from public
    domain knowledge, never from data (see SPEC section 5.2).
    """

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    unit: str
    value_type: str
    lower_bound: Decimal
    upper_bound: Decimal
    bounds_rationale: str
    contributions_per_period: int = Field(ge=1)
    statistics: list[str] = Field(default_factory=list)


class SubmissionPayload(BaseModel):
    """What an agent POSTs to /api/v1/submissions/.

    Note what is *absent*: no contributor identifier, and no collaboration
    identifier. Both are derived from the API token server-side, so an agent can
    neither submit on another contributor's behalf nor reach another
    collaboration's metrics, even if it tries.
    """

    model_config = ConfigDict(frozen=True)

    contract_version: str = CONTRACT_VERSION
    metric_code: str = Field(min_length=1, max_length=50)
    period_label: str = Field(min_length=1, max_length=16)
    value: Decimal
    n_records: int = Field(ge=1)
    agent_version: str = Field(min_length=1, max_length=32)

    @field_validator("value")
    @classmethod
    def _quantize(cls, v: Decimal) -> Decimal:
        """Round to the hub's stored precision on the client side.

        Without this the agent can send more precision than the column holds and
        the stored value silently differs from what was sent -- which would break
        the idempotency check on resubmission.
        """
        return v.quantize(Decimal(1).scaleb(-DECIMAL_PLACES))


class SubmissionAck(BaseModel):
    """Hub -> agent response. ``created`` is False when a submission was updated
    in place, which is how the agent reports an idempotent resubmission."""

    model_config = ConfigDict(frozen=True)

    id: int
    created: bool
    contributor: str
    metric_code: str
    period_label: str
    value: Decimal
