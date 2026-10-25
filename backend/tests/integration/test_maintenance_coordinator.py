"""A maintenance entry carried out end to end, on real PostgreSQL (P4 on #61).

The administrator's entry, the coordinator in the tailnet admin, and a running
node agent reached over its control routes, with the host's two parts
simulated: the witness answering challenges, and the supervisor restarting a
runtime that comes back empty.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import text

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.repositories import (
    PostgresMaintenanceOperations,
    PostgresMaintenanceRepository,
    PostgresNodeRepository,
)
from app.application.use_cases.maintenance_coordinator import MaintenanceCoordinator
from app.application.use_cases.manage_maintenance import ManageMaintenance
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.maintenance_operation import OperationStatus, StepPhase, StepStatus
from app.infrastructure.config import get_settings
from app.infrastructure.db import dispose_engine, init_engine, session_scope
from app.infrastructure.di.shared import build_audit
from app.infrastructure.maintenance_coordinator import AgentControls, PostgresCoordinatorStore
from app.node_agent.resolution import Witness
from tests.integration.node_agent_fixtures import CONTROL_TOKEN, NODE, TOKEN, running_agent
from tests.integration.test_node_agent_resolution import ENDPOINT, FakeWitness

ADMIN = Actor(
    id="admin-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
)


@pytest.fixture
async def world(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    async with running_agent(database_url, tmp_path, monkeypatch) as handles:
        out, challenge = tmp_path / "witness-out", tmp_path / "witness-challenge"
        out.mkdir()
        challenge.mkdir()
        witness = FakeWitness(out, challenge)
        producer = asyncio.create_task(witness.run())
        handles["agent"].resolutions._witness = Witness(  # noqa: SLF001
            out, challenge, expected_endpoint=ENDPOINT, timeout_s=1.0, poll_s=0.01
        )
        conn = await asyncpg.connect(handles["dsn"])
        await conn.execute("UPDATE nodes SET agent_url = 'http://agent' WHERE id = $1", NODE)
        await conn.close()

        await dispose_engine()
        get_settings.cache_clear()
        init_engine(get_settings())
        handles["witness"] = witness
        handles["controls"] = AgentControls(
            CONTROL_TOKEN, transport=httpx.ASGITransport(app=handles["app"])
        )
        try:
            yield handles
        finally:
            producer.cancel()
            await dispose_engine()


async def supervisor(world: dict[str, Any], *, answers: int = 1) -> list[dict[str, Any]]:
    """The host supervisor restarting the runtime: what was resident is gone,
    and the witness reports a new instance."""
    requests, receipts = world["supervisor"] / "requests", world["supervisor"] / "receipts"
    seen: list[dict[str, Any]] = []
    async with asyncio.timeout(20):
        while len(seen) < answers:
            for path in list(requests.iterdir()):
                if path.name.endswith(".json"):
                    request = json.loads(path.read_text())
                    path.rename(requests / f".{request['request_id']}.claimed")
                    world["ollama"].resident = []
                    pid, _ = world["witness"].instance
                    world["witness"].instance = (pid + 1, f"restarted {len(seen)}")
                    receipt = {**request, "result": "ok", "error": None, "steps": []}
                    (receipts / path.name).write_text(json.dumps(receipt))
                    seen.append(request)
            await asyncio.sleep(0.01)
    return seen


async def enter() -> int:
    async with session_scope() as session:
        state = await ManageMaintenance(
            PostgresMaintenanceRepository(session),
            RoleAuthorization(),
            build_audit(),
            enabled=True,
            operations=PostgresMaintenanceOperations(session),
            nodes=PostgresNodeRepository(session),
            agents_enabled=True,
        ).enter(ADMIN, message="runtime upgrade", expected_return_at=None)
    return state.epoch


def coordinator(world: dict[str, Any], owner: str) -> MaintenanceCoordinator:
    return MaintenanceCoordinator(
        PostgresCoordinatorStore(build_audit()), world["controls"], owner=owner
    )


async def until_settled(coord: MaintenanceCoordinator) -> Any:
    async with asyncio.timeout(30):
        while True:
            await coord.run_once()
            async with session_scope() as session:
                operation = await PostgresMaintenanceOperations(session).latest()
            if operation is not None and operation.status is not OperationStatus.RUNNING:
                return operation
            await asyncio.sleep(0.05)


async def actions() -> list[str]:
    async with session_scope() as session:
        rows = await session.execute(
            text("SELECT action FROM audit_log WHERE action LIKE 'maintenance.%' ORDER BY at")
        )
        return [r[0] for r in rows]


async def test_an_entry_releases_the_runtime_and_keeps_what_it_held(
    world: dict[str, Any],
) -> None:
    resident_before = list(world["ollama"].resident)
    epoch = await enter()
    answering = asyncio.create_task(supervisor(world))

    operation = await until_settled(coordinator(world, "c1"))
    [request] = await answering

    assert operation.status is OperationStatus.SUCCEEDED, operation
    [step] = operation.steps
    assert (step.node_id, step.phase, step.status) == (NODE, StepPhase.VERIFIED, StepStatus.DONE)
    assert step.snapshot == resident_before, "the snapshot is what the runtime held"
    assert step.snapshot_at is not None
    assert step.reset is not None and step.reset["reset_id"] == request["request_id"]
    assert step.reset_id == request["request_id"], "the supervisor request is the reset's id"
    assert step.accounting == "resolved"
    assert world["ollama"].resident == []

    status = (await world["http"].get("/v1/status", headers=_data())).json()
    assert status["gate"] == "maintenance" and status["maintenance_epoch"] == epoch
    assert await actions() == [
        "maintenance.entered",
        "maintenance.node_cleared",
        "maintenance.entry_cleared",
    ]


async def test_an_unknown_left_by_an_earlier_agent_is_resolved_by_the_reset(
    world: dict[str, Any],
) -> None:
    agent = world["agent"]
    await agent.pool.execute(
        "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
        "origin_boot_id, owner_generation, submitted_at) VALUES "
        "($1, 'orphan', 'inference', 'outcome_unknown', 1, 'an-earlier-boot', $2, now())",
        NODE,
        agent.store.ownership.generation,
    )
    await enter()
    answering = asyncio.create_task(supervisor(world))

    operation = await until_settled(coordinator(world, "c1"))
    await answering

    [step] = operation.steps
    assert step.accounting == "resolved"
    assert step.reset is not None and step.reset["resolved"] == ["orphan"]
    orphan = await agent.store.observe("orphan")
    assert orphan is not None and orphan.state == "failed"
    assert orphan.reason == "resolved_by_reset"


async def test_two_coordinators_restart_the_runtime_once(world: dict[str, Any]) -> None:
    await enter()
    answering = asyncio.create_task(supervisor(world, answers=1))

    first, second = coordinator(world, "c1"), coordinator(world, "c2")
    await asyncio.gather(until_settled(first), until_settled(second))
    await answering

    requests = world["supervisor"] / "requests"
    assert [p.name for p in requests.iterdir() if p.name.endswith(".json")] == []
    receipts = list((world["supervisor"] / "receipts").iterdir())
    assert len(receipts) == 1, receipts


async def test_the_gateway_cannot_read_an_entrys_snapshots(world: dict[str, Any]) -> None:
    from app.infrastructure.db_roles import GATEWAY_DENIED_READ_TABLES

    assert {"maintenance_operations", "maintenance_node_steps"} <= set(GATEWAY_DENIED_READ_TABLES)


def _data() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


async def test_a_restore_puts_back_what_the_entry_released_and_then_reopens(
    world: dict[str, Any],
) -> None:
    """The whole of #61's runtime half: the entry snapshots and releases, the
    restore loads the snapshot back under the hold with its weights and
    context, checks each model answers, and only then reopens."""
    ollama = world["ollama"]
    ollama.tracks_residency = True
    ollama.resident = [
        {
            "name": "qwen2.5:7b",
            "digest": ollama.digest,
            "size": 5 * 1024**3,
            "context_length": 32768,
        },
        {
            "name": "nomic-embed-text:latest",
            "digest": "c" * 64,
            "size": 300 * 1024**2,
            "context_length": 2048,
        },
    ]
    epoch = await enter()
    answering = asyncio.create_task(supervisor(world))
    entry = await until_settled(coordinator(world, "c1"))
    await answering
    assert entry.status is OperationStatus.SUCCEEDED and ollama.resident == []

    async with session_scope() as session:
        restore = await ManageMaintenance(
            PostgresMaintenanceRepository(session),
            RoleAuthorization(),
            build_audit(),
            enabled=True,
            operations=PostgresMaintenanceOperations(session),
            nodes=PostgresNodeRepository(session),
            agents_enabled=True,
        ).restore(ADMIN)
    assert restore.kind.value == "restore"

    done = await until_settled(coordinator(world, "c1"))

    assert done.status is OperationStatus.SUCCEEDED, done
    assert sorted(m["name"] for m in ollama.resident) == [
        "nomic-embed-text:latest",
        "qwen2.5:7b",
    ]
    by_name = {m["name"]: m for m in ollama.resident}
    assert by_name["qwen2.5:7b"]["context_length"] == 32768
    assert by_name["nomic-embed-text:latest"]["context_length"] == 2048
    loads = [b["model"] for b in ollama.lifecycle if not b.get("prompt")]
    assert loads == ["qwen2.5:7b", "nomic-embed-text"], "largest first"
    assert ollama.embeds == 1, "the embedder answered its probe"

    async with session_scope() as session:
        state = await PostgresMaintenanceRepository(session).read()
    assert not state.admission_closed and state.epoch == epoch
    async with asyncio.timeout(5):
        while (await world["http"].get("/v1/status", headers=_data())).json()["gate"] != "serving":
            await asyncio.sleep(0.05)
    kinds = await world["agent"].pool.fetch(
        "SELECT kind, state, provenance->>'maintenance_epoch' AS epoch FROM node_operations "
        "WHERE provenance ? 'restore' ORDER BY submitted_at"
    )
    assert [(r["kind"], r["state"]) for r in kinds] == [
        ("load", "completed"),
        ("load", "completed"),
        ("probe", "completed"),
        ("probe", "completed"),
    ]
    assert {r["epoch"] for r in kinds} == {str(epoch)}
    assert await actions() == [
        "maintenance.entered",
        "maintenance.node_cleared",
        "maintenance.entry_cleared",
        "maintenance.restore_started",
        "maintenance.node_restored",
        "maintenance.restored",
    ]


async def test_a_restore_load_is_refused_once_the_hold_is_lifted(world: dict[str, Any]) -> None:
    epoch = await enter()
    response = await world["http"].post(
        "/v1/maintenance/restore",
        json={
            "epoch": epoch + 1,
            "op_id": "restore-x",
            "action": "load",
            "name": "qwen2.5:7b",
            "digest": None,
            "context_length": None,
        },
        headers={"Authorization": f"Bearer {CONTROL_TOKEN}"},
    )
    assert response.status_code == 409
    assert response.json()["refused"] == "hold_not_closed_at_epoch"
    data = await world["http"].post(
        "/v1/maintenance/restore", json={"epoch": epoch}, headers=_data()
    )
    assert data.status_code == 401, "the data token cannot restore"


async def test_an_administrator_clears_an_unknown_operation_by_a_supervised_reset(
    world: dict[str, Any],
) -> None:
    """The console's reset (#49 §5, #61): witness baseline, supervisor restart,
    second answer, resolution; the node serves again."""
    from app.adapters.persistence.repositories import PostgresUnknownOperations
    from app.application.use_cases.reset_node_runtime import ResetNodeRuntime

    agent = world["agent"]
    await agent.pool.execute(
        "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
        "origin_boot_id, owner_generation, submitted_at) VALUES "
        "($1, 'orphan', 'inference', 'outcome_unknown', 1, 'an-earlier-boot', $2, now())",
        NODE,
        agent.store.ownership.generation,
    )
    await agent.dispatcher.reopen()
    assert (await world["http"].get("/v1/status", headers=_data())).json()["gate"] == "blocked"

    answering = asyncio.create_task(supervisor(world))
    async with session_scope() as session:
        resets = ResetNodeRuntime(
            PostgresUnknownOperations(session),
            RoleAuthorization(),
            build_audit(),
            control_for=world["controls"],
        )
        assert [u.op_id for u in await resets.list(ADMIN)] == ["orphan"]
        outcome = await resets.reset(
            ADMIN, node_id=NODE, op_id="orphan", evidence="host acceptance"
        )
    await answering

    assert outcome.cleared, outcome.detail
    orphan = await agent.store.observe("orphan")
    assert orphan is not None and orphan.state == "failed"
    assert orphan.reason == "resolved_by_reset"
    assert (await world["http"].get("/v1/status", headers=_data())).json()["gate"] == "serving"
    assert "node.runtime_reset" in [a for a in await _all_actions()]


async def _all_actions() -> list[str]:
    async with session_scope() as session:
        rows = await session.execute(text("SELECT action FROM audit_log ORDER BY at"))
        return [r[0] for r in rows]
