"""Bussola plant-side agent.

Installable without Django. That is what makes the multi-party architecture
real rather than cosmetic: the agent is a genuinely separate program, with its
own dependencies and its own credential, that happens to speak HTTP to the hub.
"""

from bussola_agent.config import AGENT_VERSION

__all__ = ["AGENT_VERSION"]
