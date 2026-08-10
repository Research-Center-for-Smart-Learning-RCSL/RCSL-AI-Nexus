"""Compute node registry: the write side, with the SSRF guard.

This is the first node write path, and by the rule in security.md section 7.2 the
guard ships with it: registering or editing a node stores an `address` the
platform will make outbound requests to (the health probe now, routing to a
second node later), so every write validates the address against the tailnet
range before it is stored. Validation goes through `EgressGuardPort` rather than
importing the guard, keeping the application layer free of adapter imports, the
same discipline model-reference validation follows.

Status is not taken from whoever fills the form. A node's status is observed by
probing the runtimes it declares (`NodeHealthPort`), both here on write and on
the periodic heartbeat, so `node.status` is a fact the router can trust rather
than an assumption that is always `online`.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import ModelStateConflictError, NodeNotFoundError
from app.domain.ports.egress_port import EgressGuardPort
from app.domain.ports.node_health_port import NodeHealthPort
from app.domain.ports.repositories import ModelRepositoryPort, NodeRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort


class ManageNodes:
    def __init__(
        self,
        nodes: NodeRepositoryPort,
        models: ModelRepositoryPort,
        egress: EgressGuardPort,
        health: NodeHealthPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._nodes = nodes
        self._models = models
        self._egress = egress
        self._health = health
        self._authz = authz
        self._audit = audit

    async def list_all(self, actor: Actor) -> list[Node]:
        self._authz.require(actor, Scope.NODE_READ)
        return await self._nodes.list_all()

    async def get(self, actor: Actor, node_id: str) -> Node:
        self._authz.require(actor, Scope.NODE_READ)
        return await self._require(node_id)

    async def register(
        self,
        actor: Actor,
        *,
        name: str,
        address: str,
        total_memory_gb: float,
        runtimes: frozenset[RuntimeKind],
    ) -> Node:
        self._authz.require(actor, Scope.NODE_WRITE)

        # Before anything is stored: a node address the platform will call must
        # be inside the tailnet. Raises InvalidNodeAddressError (400).
        await self._egress.assert_node_address_allowed(address)
        await self._require_unique_name(name)

        node = Node(
            id=str(uuid.uuid4()),
            name=name,
            address=address,
            # Overwritten by the probe below. Seeded offline so that if the probe
            # cannot reach the node, the registry does not claim it is up.
            status=NodeStatus.OFFLINE,
            total_memory_gb=total_memory_gb,
            runtimes=runtimes,
        )
        node = replace(node, status=await self._health.probe(node))
        await self._nodes.save(node)
        await self._audit.record(
            actor,
            AuditAction.NODE_REGISTERED,
            target=node.id,
            detail={"name": name, "address": address},
        )
        return node

    async def update(
        self,
        actor: Actor,
        node_id: str,
        *,
        name: str | None = None,
        address: str | None = None,
        total_memory_gb: float | None = None,
        runtimes: frozenset[RuntimeKind] | None = None,
    ) -> Node:
        self._authz.require(actor, Scope.NODE_WRITE)
        node = await self._require(node_id)

        if address is not None and address != node.address:
            await self._egress.assert_node_address_allowed(address)
        if name is not None and name != node.name:
            await self._require_unique_name(name)

        updated = replace(
            node,
            name=name if name is not None else node.name,
            address=address if address is not None else node.address,
            total_memory_gb=(
                total_memory_gb if total_memory_gb is not None else node.total_memory_gb
            ),
            runtimes=runtimes if runtimes is not None else node.runtimes,
        )
        # Re-observe: an address or runtime change can move a node that was
        # online offline and the reverse, and a stale status would misroute.
        updated = replace(updated, status=await self._health.probe(updated))
        await self._nodes.save(updated)
        await self._audit.record(actor, AuditAction.NODE_UPDATED, target=node.id)
        return updated

    async def delete(self, actor: Actor, node_id: str) -> None:
        self._authz.require(actor, Scope.NODE_WRITE)
        node = await self._require(node_id)

        # `models.node_id` is a foreign key, so the database would refuse this
        # anyway, but as an IntegrityError at flush that surfaces as a 500 after
        # the response has been sent. Refusing here turns it into a 409 with a
        # message that says which node and why.
        attached = [m.alias for m in await self._models.list_all() if m.node_id == node_id]
        if attached:
            raise ModelStateConflictError(
                detail=f"node {node_id} still has models registered: {', '.join(sorted(attached))}"
            )

        await self._nodes.delete(node.id)
        await self._audit.record(
            actor, AuditAction.NODE_REMOVED, target=node.id, detail={"name": node.name}
        )

    async def check_health(self, actor: Actor, node_id: str) -> Node:
        """Probe a node now and persist the observed status.

        The UI's refresh action and, indirectly, the operator who wants an answer
        without waiting for the next heartbeat. A read scope: it observes a node
        and writes only the derived status, never configuration.
        """
        self._authz.require(actor, Scope.NODE_READ)
        node = await self._require(node_id)
        status = await self._health.probe(node)
        await self._nodes.set_status(node.id, status)
        return replace(node, status=status)

    async def _require(self, node_id: str) -> Node:
        node = await self._nodes.get(node_id)
        if node is None:
            raise NodeNotFoundError(detail=f"no node {node_id}")
        return node

    async def _require_unique_name(self, name: str) -> None:
        # Consistent with how ManageModels reports a taken alias: a friendly
        # conflict rather than the database's unique-violation 500. The node
        # table is tiny, so a full scan costs nothing.
        if any(n.name == name for n in await self._nodes.list_all()):
            raise ModelStateConflictError(detail=f"a node named {name!r} already exists")
