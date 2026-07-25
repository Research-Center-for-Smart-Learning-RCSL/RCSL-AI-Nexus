"""Observing a node's status, so `node.status` is a fact rather than an assumption.

Phase 1 wrote every node `online` at provision and never revisited it, which made
a routing requirement of `node_status: [online]` inert: it always held. This port
lets a heartbeat replace the constant with an observation, so a policy that
demands an online node actually stops routing to one whose runtime has gone away.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.node import Node, NodeStatus


class NodeHealthPort(Protocol):
    async def probe(self, node: Node) -> NodeStatus:
        """Return an observed status for the node.

        `online` when every runtime it declares answers, `degraded` when only
        some do, `offline` when none does or there is nothing this build can
        probe. The reading is deliberately conservative: an unverifiable node is
        not reported healthy.
        """
        ...
