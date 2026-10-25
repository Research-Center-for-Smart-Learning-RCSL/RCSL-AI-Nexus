"""Clearing a node's unknown operation from the console (#49 §5, moved to #61).

An operation the node sent and has no terminal evidence for is `outcome_unknown`
and blocks the node: nothing more is dispatched to it until the runtime that may
have received it is proven gone. Until now an operator proved that with the
reset CLI on the host. This is the same action for a platform administrator:
the node agent takes a witness baseline, has the host supervisor restart the
runtime, takes a second answer that must show a new instance, and only then
resolves the operation, as `failed / resolved_by_reset`, with the evidence.

Elapsed time, an unanswered node or a runtime that answers are never evidence;
the agent refuses without the witness, and the refusal is shown as it is. The
restart unloads every model on the node; the residency reconciler loads the
resident set back.

Only the tailnet admin holds the agents' control token, so only there can this
run. Elsewhere it is refused before anything is sent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance_operation import UnknownOperation
from app.domain.exceptions import (
    MaintenanceStateConflictError,
    MaintenanceUnsupportedError,
    NotAuthorizedError,
)
from app.domain.ports.node_control_port import NodeControlError, NodeControlPort
from app.domain.ports.repositories import UnknownOperationsPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

ControlFor = Callable[[str], Awaitable[NodeControlPort | None]]


@dataclass(frozen=True, slots=True)
class ResetOutcome:
    node_id: str
    op_id: str
    cleared: bool
    detail: str
    """What the agent answered: the gate it left the node in, or why it
    refused. Shown to the administrator as it is."""
    result: dict[str, Any] = field(default_factory=dict)


class ResetNodeRuntime:
    def __init__(
        self,
        unknowns: UnknownOperationsPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        *,
        control_for: ControlFor | None,
    ) -> None:
        self._unknowns = unknowns
        self._authz = authz
        self._audit = audit
        self._control_for = control_for

    @property
    def available(self) -> bool:
        return self._control_for is not None

    async def list(self, actor: Actor) -> list[UnknownOperation]:
        self._require(actor, Scope.MAINTENANCE_READ)
        return await self._unknowns.list()

    async def reset(self, actor: Actor, *, node_id: str, op_id: str, evidence: str) -> ResetOutcome:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        if self._control_for is None:
            raise MaintenanceUnsupportedError(
                detail="runtime control is only available on the tailnet admin"
            )
        if not any(u.node_id == node_id and u.op_id == op_id for u in await self._unknowns.list()):
            raise MaintenanceStateConflictError(detail=f"{op_id} is not unknown on {node_id}")
        control = await self._control_for(node_id)
        if control is None:
            raise MaintenanceUnsupportedError(detail=f"{node_id} has no agent to reset through")

        operator = f"{actor.display} ({actor.id})"
        try:
            result = await control.resolve_by_reset(op_id, operator=operator, evidence=evidence)
        except NodeControlError as exc:
            refused = exc.body.get("refused") if isinstance(exc.body, dict) else None
            detail = str(refused or exc)
            await self._audit.record(
                actor,
                AuditAction.NODE_RUNTIME_RESET,
                target=node_id,
                outcome="failed",
                detail={"op_id": op_id, "error": detail[:500]},
            )
            return ResetOutcome(node_id=node_id, op_id=op_id, cleared=False, detail=detail)

        await self._audit.record(
            actor,
            AuditAction.NODE_RUNTIME_RESET,
            target=node_id,
            detail={"op_id": op_id, "gate": str(result.get("gate"))},
        )
        return ResetOutcome(
            node_id=node_id,
            op_id=op_id,
            cleared=True,
            detail=f"cleared; the node's gate is {result.get('gate')}",
            result=result,
        )

    def _require(self, actor: Actor, scope: Scope) -> None:
        self._authz.require(actor, scope)
        if actor.role is not Role.ADMIN:
            raise NotAuthorizedError(
                detail=f"a runtime reset needs a platform admin, not {actor.role}"
            )
