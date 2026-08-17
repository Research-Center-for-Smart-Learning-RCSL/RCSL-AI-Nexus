"""Node registry writes, the SSRF guard, and status as an observation.

The load-bearing cases: the egress guard runs before an address is stored, a
node with models attached cannot be deleted out from under them, and status is
whatever the probe observed rather than whatever the form said.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_nodes import ManageNodes
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import (
    InvalidNodeAddressError,
    NodeNotFoundError,
    NodeStateConflictError,
    NotAuthorizedError,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeEgressGuard,
    FakeModels,
    FakeNodeHealth,
    FakeNodes,
)

ADMIN = Actor(
    id="admin-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
)
READER = Actor(
    id="u2", display="user", role=Role.USER, source="local", scopes=frozenset({Scope.NODE_READ})
)

EXISTING = Node(
    id="node-1",
    name="studio",
    address="100.64.0.1",
    status=NodeStatus.ONLINE,
    total_memory_gb=64.0,
    runtimes=frozenset({RuntimeKind.OLLAMA}),
)


def build(
    *,
    nodes=(),
    models=(),
    blocked=frozenset(),
    health_status=NodeStatus.ONLINE,
) -> tuple[ManageNodes, FakeNodes, FakeEgressGuard, FakeNodeHealth, FakeAudit]:
    node_repo = FakeNodes(nodes)
    egress = FakeEgressGuard(blocked=blocked)
    health = FakeNodeHealth(status=health_status)
    audit = FakeAudit()
    use_case = ManageNodes(
        nodes=node_repo,
        models=FakeModels(models),
        egress=egress,
        health=health,
        authz=RoleAuthorization(),
        audit=audit,
    )
    return use_case, node_repo, egress, health, audit


async def test_register_checks_the_egress_guard_before_storing() -> None:
    nodes, repo, egress, health, audit = build()

    node = await nodes.register(
        ADMIN,
        name="second",
        address="100.90.0.5",
        total_memory_gb=32.0,
        runtimes=frozenset({RuntimeKind.MLX}),
    )

    assert egress.checked == ["100.90.0.5"], "the address must be guarded before it is stored"
    assert repo.rows[node.id].address == "100.90.0.5"
    assert node.status is NodeStatus.ONLINE, "status is the probe's observation"
    assert health.probed == [node.id]
    assert "node.registered" in audit.actions()


async def test_register_refuses_an_off_tailnet_address_and_stores_nothing() -> None:
    nodes, repo, egress, health, audit = build(blocked=frozenset({"169.254.169.254"}))

    with pytest.raises(InvalidNodeAddressError):
        await nodes.register(
            ADMIN,
            name="evil",
            address="169.254.169.254",
            total_memory_gb=32.0,
            runtimes=frozenset({RuntimeKind.OLLAMA}),
        )

    assert repo.rows == {}, "a refused address must never be stored"
    assert "node.registered" not in audit.actions()


async def test_register_refuses_a_duplicate_name() -> None:
    nodes, _, _, _, _ = build(nodes=(EXISTING,))

    with pytest.raises(NodeStateConflictError):
        await nodes.register(
            ADMIN,
            name="studio",
            address="100.90.0.5",
            total_memory_gb=32.0,
            runtimes=frozenset({RuntimeKind.OLLAMA}),
        )


async def test_register_requires_node_write() -> None:
    nodes, _, _, _, _ = build()

    with pytest.raises(NotAuthorizedError):
        await nodes.register(
            READER,
            name="second",
            address="100.90.0.5",
            total_memory_gb=32.0,
            runtimes=frozenset({RuntimeKind.OLLAMA}),
        )


async def test_update_reguards_a_changed_address() -> None:
    nodes, _, egress, _, _ = build(nodes=(EXISTING,), blocked=frozenset({"10.0.0.9"}))

    with pytest.raises(InvalidNodeAddressError):
        await nodes.update(ADMIN, EXISTING.id, address="10.0.0.9")

    assert egress.checked == ["10.0.0.9"]


async def test_update_does_not_reguard_an_unchanged_address() -> None:
    nodes, _, egress, _, _ = build(nodes=(EXISTING,))

    await nodes.update(ADMIN, EXISTING.id, total_memory_gb=48.0)

    assert egress.checked == [], "an edit that leaves the address alone needs no DNS check"


async def test_update_reobserves_status() -> None:
    nodes, repo, _, health, _ = build(nodes=(EXISTING,), health_status=NodeStatus.OFFLINE)

    updated = await nodes.update(ADMIN, EXISTING.id, total_memory_gb=48.0)

    assert updated.status is NodeStatus.OFFLINE
    assert repo.rows[EXISTING.id].total_memory_gb == 48.0


async def test_delete_is_refused_while_models_are_attached() -> None:
    model = Model(
        id="m1",
        alias="chat-main",
        ref="library/qwen2.5:7b",
        runtime=RuntimeKind.OLLAMA,
        node_id=EXISTING.id,
        state=ModelState.DOWNLOADED,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=8.0, context_length=8192),
    )
    nodes, repo, _, _, _ = build(nodes=(EXISTING,), models=(model,))

    with pytest.raises(NodeStateConflictError):
        await nodes.delete(ADMIN, EXISTING.id)

    assert EXISTING.id in repo.rows, "the node must survive a refused delete"


async def test_delete_removes_a_node_with_no_models_and_audits_it() -> None:
    nodes, repo, _, _, audit = build(nodes=(EXISTING,))

    await nodes.delete(ADMIN, EXISTING.id)

    assert EXISTING.id not in repo.rows
    assert "node.removed" in audit.actions()


async def test_check_health_probes_and_persists_the_status() -> None:
    nodes, repo, _, health, _ = build(nodes=(EXISTING,), health_status=NodeStatus.DEGRADED)

    result = await nodes.check_health(ADMIN, EXISTING.id)

    assert result.status is NodeStatus.DEGRADED
    assert repo.rows[EXISTING.id].status is NodeStatus.DEGRADED
    assert health.probed == [EXISTING.id]


async def test_missing_node_is_a_domain_not_found() -> None:
    nodes, _, _, _, _ = build()

    with pytest.raises(NodeNotFoundError):
        await nodes.get(ADMIN, "does-not-exist")
