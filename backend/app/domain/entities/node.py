"""Compute node entity.

Live metrics (CPU, temperature) are deliberately not fields here: they are
read through `MetricsPort` in Phase 2. `total_memory_gb` is static capacity
and is what the Phase 1 memory budget check works from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.domain.entities.model import RuntimeKind


class NodeStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    name: str
    address: str
    """Tailscale address. Validated against the tailnet range before any
    outbound request; see adapters/http/egress_guard.py."""

    status: NodeStatus
    total_memory_gb: float
    runtimes: frozenset[RuntimeKind] = field(default_factory=frozenset)
    agent_url: str | None = None
    """Where this node's agent is reached (PR4a on #24). None for a node with
    no agent, which the agent path refuses rather than reaching around."""
    runtime_version: str | None = None
    runtime_version_at: datetime | None = None
    """The runtime's version as the heartbeat last read it, and when: one part
    of a validated profile's key, used only while fresh (PR2b on #24)."""
