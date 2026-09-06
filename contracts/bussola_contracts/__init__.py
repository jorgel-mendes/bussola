"""Wire contract shared by the Bussola agent and the hub.

This package is the *single* definition of the agent -> hub payload. Both sides
import it, so a change to the wire format is a change to one file and the
contract test in ``hub/ingest/test_contract.py`` fails loudly if the hub's
serializer and this schema drift apart.

Keep this package dependency-light (pydantic only). The agent must be
installable on a plant machine without pulling in Django.
"""

from bussola_contracts.position import PositionReport
from bussola_contracts.submissions import (
    CONTRACT_VERSION,
    MetricSpec,
    SubmissionAck,
    SubmissionPayload,
)

__all__ = [
    "CONTRACT_VERSION",
    "MetricSpec",
    "PositionReport",
    "SubmissionAck",
    "SubmissionPayload",
]
