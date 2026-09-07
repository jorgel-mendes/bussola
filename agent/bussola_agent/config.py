"""Agent configuration.

Read from environment variables so the agent runs the same way under
docker-compose, systemd, or a cron entry on a contributor's machine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

AGENT_VERSION = "0.1.0"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class AgentConfig:
    hub_url: str
    token: str
    contributor_label: str = "unnamed-contributor"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> AgentConfig:
        hub_url = os.environ.get("BUSSOLA_HUB_URL", "").rstrip("/")
        token = os.environ.get("BUSSOLA_TOKEN", "")

        missing = [
            name
            for name, value in (("BUSSOLA_HUB_URL", hub_url), ("BUSSOLA_TOKEN", token))
            if not value
        ]
        if missing:
            raise ConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set BUSSOLA_HUB_URL to the hub base URL and BUSSOLA_TOKEN to the "
                "API token issued for this contributor."
            )

        return cls(
            hub_url=hub_url,
            token=token,
            contributor_label=os.environ.get("BUSSOLA_CONTRIBUTOR_LABEL", "unnamed-contributor"),
            timeout_seconds=float(os.environ.get("BUSSOLA_TIMEOUT", "30")),
        )
