"""An administrator clearing a node's unknown operation from the console (#61)."""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.reset_node_runtime import ResetNodeRuntime
from app.domain.entities.actor import ROLE_SCOPES, Actor, Role, Scope
from app.domain.entities.maintenance_operation import UnknownOperation
from app.domain.exceptions import (
    MaintenanceStateConflictError,
    MaintenanceUnsupportedError,
    NotAuthorizedError,
)
from app.domain.ports.node_control_port import NodeControlError, NodeControlPort
from tests.unit.fakes import FakeAudit

ADMIN = Actor(id="a-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope))
OPERATOR = Actor(
    id="o-1", display="op", role=Role.OPERATOR, source="tailnet", scopes=ROLE_SCOPES[Role.OPERATOR]
)
BLOCKED = UnknownOperation("local", "op-1", "inference", "relay_cancelled", None)


class Unknowns:
    def __init__(self, *rows: UnknownOperation) -> None:
        self.rows = list(rows)

    async def list(self) -> list[UnknownOperation]:
        return list(self.rows)


class Agent:
    def __init__(self, refusal: NodeControlError | None = None) -> None:
        self.refusal = refusal
        self.calls: list[tuple[str, str, str]] = []

    async def resolve_by_reset(self, op_id: str, *, operator: str, evidence: str) -> dict[str, Any]:
        self.calls.append((op_id, operator, evidence))
        if self.refusal:
            raise self.refusal
        return {"op_id": op_id, "state": "failed", "gate": "serving"}


def build(agent: Agent | None) -> tuple[ResetNodeRuntime, FakeAudit]:
    audit = FakeAudit()

    async def control_for(node_id: str) -> NodeControlPort | None:
        return agent  # type: ignore[return-value]

    use_case = ResetNodeRuntime(
        Unknowns(BLOCKED),
        RoleAuthorization(),
        audit,
        control_for=control_for if agent is not None else None,
    )
    return use_case, audit


async def test_a_reset_clears_the_operation_and_records_who_and_why() -> None:
    agent = Agent()
    use_case, audit = build(agent)

    outcome = await use_case.reset(ADMIN, node_id="local", op_id="op-1", evidence="host rebooted")

    assert outcome.cleared and "serving" in outcome.detail
    assert agent.calls == [("op-1", "admin (a-1)", "host rebooted")]
    assert audit.entries[-1][0] == "node.runtime_reset"


async def test_an_agent_refusal_is_shown_as_it_is_and_audited_failed() -> None:
    agent = Agent(
        NodeControlError(
            "409", status=409, body={"refused": "the runtime witness did not answer the challenge"}
        )
    )
    use_case, audit = build(agent)

    outcome = await use_case.reset(ADMIN, node_id="local", op_id="op-1", evidence="x")

    assert not outcome.cleared
    assert "witness did not answer" in outcome.detail
    assert audit.entries[-1][0] == "node.runtime_reset"


async def test_only_an_operation_still_unknown_on_that_node_is_reset() -> None:
    agent = Agent()
    use_case, _ = build(agent)
    with pytest.raises(MaintenanceStateConflictError):
        await use_case.reset(ADMIN, node_id="other", op_id="op-1", evidence="x")
    assert agent.calls == []


async def test_without_the_control_token_nothing_is_sent() -> None:
    use_case, _ = build(None)
    assert not use_case.available
    assert await use_case.list(ADMIN) == [BLOCKED]
    with pytest.raises(MaintenanceUnsupportedError):
        await use_case.reset(ADMIN, node_id="local", op_id="op-1", evidence="x")


async def test_only_a_platform_admin_resets() -> None:
    use_case, _ = build(Agent())
    with pytest.raises(NotAuthorizedError):
        await use_case.reset(OPERATOR, node_id="local", op_id="op-1", evidence="x")
