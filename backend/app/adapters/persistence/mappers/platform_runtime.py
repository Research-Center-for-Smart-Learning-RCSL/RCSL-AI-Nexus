"""Persistence platform runtime boundary."""

from __future__ import annotations

from typing import Any

from app.adapters.persistence.sqlalchemy_models import (
    ModelRow,
    NodeRow,
    RoutingPolicyRow,
    TenantRow,
)
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import (
    Requirement,
    RoutingCandidate,
    RoutingPolicy,
)
from app.domain.entities.tenant import Tenant


def tenant_to_domain(row: TenantRow) -> Tenant:
    return Tenant(id=row.id, name=row.name, created_at=row.created_at)


def tenant_to_row(tenant: Tenant) -> TenantRow:
    row = TenantRow(id=tenant.id, name=tenant.name)
    if tenant.created_at is not None:
        row.created_at = tenant.created_at
    return row


def node_to_domain(row: NodeRow) -> Node:
    return Node(
        id=row.id,
        name=row.name,
        address=row.address,
        status=NodeStatus(row.status),
        total_memory_gb=row.total_memory_gb,
        runtimes=frozenset(RuntimeKind(r) for r in row.runtimes or []),
    )


def node_to_row(node: Node) -> NodeRow:
    return NodeRow(
        id=node.id,
        name=node.name,
        address=node.address,
        status=node.status.value,
        total_memory_gb=node.total_memory_gb,
        runtimes=sorted(r.value for r in node.runtimes),
    )


def model_to_domain(row: ModelRow) -> Model:
    return Model(
        id=row.id,
        alias=row.alias,
        ref=row.ref,
        runtime=RuntimeKind(row.runtime),
        node_id=row.node_id,
        state=ModelState(row.state),
        capabilities=frozenset(row.capabilities or []),
        resource_profile=ResourceProfile(
            memory_gb=row.memory_gb,
            context_length=row.context_length,
        ),
        observed_state=ModelState(row.observed_state) if row.observed_state else None,
        observed_memory_gb=row.observed_memory_gb,
        observed_at=row.observed_at,
    )


def model_to_row(model: Model) -> ModelRow:
    return ModelRow(
        id=model.id,
        alias=model.alias,
        ref=model.ref,
        runtime=model.runtime.value,
        node_id=model.node_id,
        state=model.state.value,
        capabilities=sorted(model.capabilities),
        memory_gb=model.resource_profile.memory_gb,
        context_length=model.resource_profile.context_length,
        observed_state=model.observed_state.value if model.observed_state else None,
        observed_memory_gb=model.observed_memory_gb,
        observed_at=model.observed_at,
    )


def _requirement_to_json(req: Requirement) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if req.node_status:
        payload["node_status"] = sorted(s.value for s in req.node_status)
    if req.model_state:
        payload["model_state"] = sorted(s.value for s in req.model_state)
    if req.min_free_memory_gb is not None:
        payload["min_free_memory_gb"] = req.min_free_memory_gb
    return payload


def _requirement_from_json(payload: dict[str, Any] | None) -> Requirement:
    payload = payload or {}
    return Requirement(
        node_status=frozenset(NodeStatus(s) for s in payload.get("node_status", [])),
        model_state=frozenset(ModelState(s) for s in payload.get("model_state", [])),
        min_free_memory_gb=payload.get("min_free_memory_gb"),
    )


def routing_policy_to_domain(row: RoutingPolicyRow) -> RoutingPolicy:
    candidates = tuple(
        RoutingCandidate(
            model_alias=entry["model_alias"],
            priority=int(entry.get("priority", 0)),
            require=_requirement_from_json(entry.get("require")),
        )
        for entry in row.candidates or []
    )
    return RoutingPolicy(capability=row.capability, candidates=candidates, thinking=row.thinking)


def routing_policy_to_row(policy: RoutingPolicy) -> RoutingPolicyRow:
    return RoutingPolicyRow(
        capability=policy.capability,
        candidates=[
            {
                "model_alias": c.model_alias,
                "priority": c.priority,
                "require": _requirement_to_json(c.require),
            }
            for c in policy.candidates
        ],
        thinking=policy.thinking,
    )
