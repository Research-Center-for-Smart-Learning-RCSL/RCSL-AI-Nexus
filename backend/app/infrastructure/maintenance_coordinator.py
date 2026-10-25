"""Wiring for the maintenance coordinator loop (P4 on #61).

It runs in the tailnet admin beside the heartbeat, the process that holds the
node agents' control token; the gateway and the public admin never mount it.
Every store method below is its own short transaction, and no transaction is
open while a node is called. Two coordinators, or a restarted one overlapping
its predecessor, are kept apart by the operation's lease
(`repositories/maintenance_operations.py`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import FastAPI

from app.adapters.persistence.repositories import (
    PostgresMaintenanceOperations,
    PostgresMaintenanceRepository,
    PostgresNodeRepository,
)
from app.adapters.runtime.node_agent_control import NodeAgentControl
from app.application.audit_subject import (
    MAINTENANCE_COORDINATOR_ID,
    maintenance_coordinator_subject,
)
from app.application.use_cases.maintenance_coordinator import MaintenanceCoordinator
from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance import MaintenanceState
from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    NodeStep,
    OperationStatus,
    StepPhase,
)
from app.domain.ports.node_control_port import NodeControlPort
from app.domain.ports.security_ports import AuditPort
from app.infrastructure.config import Settings
from app.infrastructure.db import session_scope
from app.infrastructure.runtime_directory import MIN_AGENT_TOKEN_LENGTH

logger = logging.getLogger(__name__)

ACTIVE_INTERVAL_S = 2.0
IDLE_INTERVAL_S = 5.0


class PostgresCoordinatorStore:
    def __init__(self, audit: AuditPort) -> None:
        self._audit = audit
        self._subject = maintenance_coordinator_subject()

    async def hold(self) -> MaintenanceState:
        async with session_scope() as session:
            return await PostgresMaintenanceRepository(session).read()

    async def claim(self, *, owner: str, lease_s: float) -> MaintenanceOperation | None:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).claim(owner=owner, lease_s=lease_s)

    async def renew(self, operation_id: str, *, owner: str, lease_s: float) -> bool:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).renew(
                operation_id, owner=owner, lease_s=lease_s
            )

    async def get(self, operation_id: str) -> MaintenanceOperation | None:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).get(operation_id)

    async def advance(self, step: NodeStep, *, owner: str, phase: StepPhase, **values: Any) -> bool:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).advance(
                step, owner=owner, phase=phase, **values
            )

    async def set_reset_id(self, step: NodeStep, *, owner: str, reset_id: str) -> bool:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).set_reset_id(
                step, owner=owner, reset_id=reset_id
            )

    async def attempt_failed(
        self,
        step: NodeStep,
        *,
        owner: str,
        error: str,
        max_attempts: int,
        clear_reset_id: bool = False,
        final: bool = False,
    ) -> NodeStep | None:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).attempt_failed(
                step,
                owner=owner,
                error=error,
                max_attempts=max_attempts,
                clear_reset_id=clear_reset_id,
                final=final,
            )

    async def finish(
        self, operation_id: str, *, owner: str, status: OperationStatus, error: str | None = None
    ) -> bool:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).finish(
                operation_id, owner=owner, status=status, error=error
            )

    async def rewind(self, step: NodeStep, *, owner: str, phase: StepPhase) -> bool:
        async with session_scope() as session:
            return await PostgresMaintenanceOperations(session).rewind(
                step, owner=owner, phase=phase
            )

    async def reopen_after(self, operation_id: str, *, owner: str, epoch: int) -> bool:
        try:
            async with session_scope() as session:
                if not await PostgresMaintenanceOperations(session).finish(
                    operation_id, owner=owner, status=OperationStatus.SUCCEEDED
                ):
                    raise _NotCommitted
                opened = await PostgresMaintenanceRepository(session).reopen(
                    changed_by=MAINTENANCE_COORDINATOR_ID
                )
                if opened is None or opened.epoch != epoch:
                    raise _NotCommitted
        except _NotCommitted:
            return False
        return True

    async def audit(
        self,
        action: AuditAction,
        *,
        target: str,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None:
        await self._audit.record(
            self._subject, action, target=target, outcome=outcome, detail=detail
        )


class _NotCommitted(Exception):
    """Rolls the serving commit back: both halves land, or neither."""


class AgentControls:
    """A control client per node agent, built from the node's `agent_url`
    as it is now; None for a node without one, or with no control token."""

    def __init__(
        self, control_token: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._token = control_token
        self._transport = transport

    async def __call__(self, node_id: str) -> NodeControlPort | None:
        if not self._token:
            return None
        async with session_scope() as session:
            node = await PostgresNodeRepository(session).get(node_id)
        if node is None or not node.agent_url:
            return None
        return NodeAgentControl(node.agent_url, self._token, transport=self._transport)


def coordinator_should_run(app: FastAPI, settings: Settings) -> bool:
    """Only with node agents and a usable control token. Without one, an entry
    still closes the platform, and its steps fail visibly for want of a
    coordinator to carry them out rather than claiming anything was released."""
    if not getattr(app.state.runtimes, "agents_enabled", False):
        return False
    if not control_token_usable(settings):
        if settings.node_agent_control_token or settings.maintenance_enabled:
            logger.error(
                "the maintenance coordinator needs node_agent_control_token: at least %d "
                "characters and different from node_agent_token; it is not started",
                MIN_AGENT_TOKEN_LENGTH,
            )
        return False
    return True


def control_token_usable(settings: Settings) -> bool:
    token = settings.node_agent_control_token
    return len(token) >= MIN_AGENT_TOKEN_LENGTH and token != settings.node_agent_token


def agent_controls(app: FastAPI, settings: Settings) -> AgentControls | None:
    """The control clients, where this process may use them: the tailnet
    admin with a usable token. None elsewhere, which refuses runtime control
    before anything is sent."""
    if not getattr(app.state.runtimes, "agents_enabled", False):
        return None
    if not control_token_usable(settings):
        return None
    return AgentControls(settings.node_agent_control_token)


def build_coordinator(app: FastAPI, settings: Settings) -> MaintenanceCoordinator:
    return MaintenanceCoordinator(
        PostgresCoordinatorStore(app.state.audit),
        AgentControls(settings.node_agent_control_token),
    )


async def run_maintenance_coordinator(app: FastAPI, settings: Settings) -> None:
    coordinator = build_coordinator(app, settings)
    worked = False
    while True:
        # Sleep first, as the heartbeat does, so a lifespan that opens and
        # closes quickly never reaches the database or a node.
        await asyncio.sleep(ACTIVE_INTERVAL_S if worked else IDLE_INTERVAL_S)
        try:
            worked = await coordinator.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed pass must not kill the loop
            logger.exception("maintenance coordinator pass failed")
            worked = False
