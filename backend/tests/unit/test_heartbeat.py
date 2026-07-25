"""The node heartbeat sweep.

The one behaviour worth pinning: status is written only where the probe observed
a change, so both admin entrances running the loop do not churn the table with
identical writes every interval.
"""

from __future__ import annotations

from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.infrastructure.heartbeat import sweep
from tests.unit.fakes import FakeNodeHealth


def _node(node_id: str, status: NodeStatus) -> Node:
    return Node(
        id=node_id,
        name=node_id,
        address="100.64.0.1",
        status=status,
        total_memory_gb=64.0,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )


async def test_sweep_writes_only_changed_statuses() -> None:
    nodes = [_node("a", NodeStatus.ONLINE), _node("b", NodeStatus.ONLINE)]
    writes: list[tuple[str, NodeStatus]] = []

    async def source() -> list[Node]:
        return nodes

    async def writer(node_id: str, status: NodeStatus) -> None:
        writes.append((node_id, status))

    # The probe says everyone is offline; both nodes were online, so both move.
    changed = await sweep(FakeNodeHealth(status=NodeStatus.OFFLINE), source, writer)

    assert changed == 2
    assert writes == [("a", NodeStatus.OFFLINE), ("b", NodeStatus.OFFLINE)]


async def test_sweep_is_silent_when_nothing_changed() -> None:
    nodes = [_node("a", NodeStatus.ONLINE)]
    writes: list[tuple[str, NodeStatus]] = []

    async def source() -> list[Node]:
        return nodes

    async def writer(node_id: str, status: NodeStatus) -> None:
        writes.append((node_id, status))

    changed = await sweep(FakeNodeHealth(status=NodeStatus.ONLINE), source, writer)

    assert changed == 0
    assert writes == [], "an unchanged status must not be rewritten every interval"
