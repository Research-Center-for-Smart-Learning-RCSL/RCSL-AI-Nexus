"""The node agent and the maintenance hold, on real PostgreSQL (P3 on #61).

The database fence an entry and a promotion share, an agent that starts during
maintenance, the separate control token, and the interrupt and runtime-control
routes. The hold is changed here with SQL, the way the migrated row looks after
an administrator's entry; the audited use case that writes it is covered in
`test_maintenance_admin.py`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import PostgresMaintenanceRepository
from app.domain.entities.maintenance import FENCE_LOCK
from tests.integration.node_agent_fixtures import AUTH, CONTROL, running_agent
from tests.integration.test_node_agent_api import _generation


async def hold(dsn: str, closed: bool) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        epoch: int = await conn.fetchval(
            "UPDATE maintenance_control SET admission_closed = $1, "
            "phase = CASE WHEN $1 THEN 'maintenance' ELSE 'normal' END, "
            "epoch = epoch + CASE WHEN $1 THEN 1 ELSE 0 END, revision = revision + 1 "
            "WHERE id = 1 RETURNING epoch",
            closed,
        )
    finally:
        await conn.close()
    return epoch


def _dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture
async def client(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    async with running_agent(database_url, tmp_path, monkeypatch) as handles:
        yield handles


async def gate(client: dict[str, Any]) -> str:
    status: str = (await client["http"].get("/v1/status", headers=AUTH)).json()["gate"]
    return status


async def until_gate(client: dict[str, Any], wanted: str) -> None:
    async with asyncio.timeout(5):
        while await gate(client) != wanted:
            await asyncio.sleep(0.02)


async def test_a_closed_hold_refuses_promotion_and_reopening_restores_service(
    client: dict[str, Any],
) -> None:
    await hold(client["dsn"], True)

    refused = await client["http"].post("/v1/inference", json=_generation("m-1"), headers=AUTH)

    assert refused.status_code == 503
    assert refused.json()["refused"] == "maintenance_before_send"
    assert client["ollama"].chats == 0
    assert await gate(client) == "maintenance"
    row = (await client["http"].get("/v1/attempts/m-1", headers=AUTH)).json()
    assert row["state"] == "cancelled_unsent"

    await hold(client["dsn"], False)
    await until_gate(client, "serving")
    async with client["http"].stream(
        "POST", "/v1/inference", json=_generation("m-2"), headers=AUTH
    ) as response:
        assert response.status_code == 200
        lines = [json.loads(line) async for line in response.aiter_lines() if line.strip()]
    assert lines[-1]["state"] == "completed"


async def test_an_agent_started_during_maintenance_never_serves(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epoch = await hold(_dsn(database_url), True)
    async with running_agent(database_url, tmp_path, monkeypatch) as client:
        status = (await client["http"].get("/v1/status", headers=AUTH)).json()
        assert status["gate"] == "maintenance"
        assert status["maintenance_epoch"] == epoch


async def test_control_routes_take_the_control_token_and_nothing_else(
    client: dict[str, Any],
) -> None:
    http = client["http"]
    for path in ("/v1/drain", "/v1/resume", "/v1/maintenance/resolutions"):
        assert (await http.post(path, headers=AUTH)).status_code == 401, path
    # Nor does the control token open the data routes.
    assert (
        await http.post("/v1/inference", json=_generation("m-3"), headers=CONTROL)
    ).status_code == 401
    # Status only reads, and the resolve CLI holds only the control token.
    assert (await http.get("/v1/status", headers=CONTROL)).status_code == 200
    assert (await http.post("/v1/resume", headers=CONTROL)).json()["gate"] == "serving"


async def test_without_a_control_token_the_control_routes_refuse(
    client: dict[str, Any],
) -> None:
    client["agent"].settings.control_token = None
    response = await client["http"].post("/v1/drain", headers=CONTROL)
    assert response.status_code == 503


async def test_an_interrupt_lands_only_on_the_hold_it_names(client: dict[str, Any]) -> None:
    http = client["http"]
    open_ = await http.post("/v1/maintenance/interrupt", json={"epoch": 0}, headers=CONTROL)
    assert open_.status_code == 409 and open_.json()["refused"] == "hold_not_closed_at_epoch"

    epoch = await hold(client["dsn"], True)
    stale = await http.post("/v1/maintenance/interrupt", json={"epoch": epoch - 1}, headers=CONTROL)
    assert stale.status_code == 409

    done = await http.post("/v1/maintenance/interrupt", json={"epoch": epoch}, headers=CONTROL)

    assert done.status_code == 200
    assert done.json() | {"gate": "maintenance"} == {
        "epoch": epoch,
        "interrupted": [],
        "still_sending": [],
        "settling": [],
        "quiescent": True,
        "gate": "maintenance",
    }
    events = await client["agent"].pool.fetch(
        "SELECT event FROM node_operation_audit WHERE event = 'maintenance_interrupt'"
    )
    assert len(events) == 1


async def answer(directory: Path, *, result: str = "ok") -> dict[str, Any]:
    """The host supervisor's part: claim the first request, write a receipt."""
    requests, receipts = directory / "requests", directory / "receipts"
    async with asyncio.timeout(5):
        while True:
            for path in requests.iterdir():
                if path.name.endswith(".json"):
                    request = json.loads(path.read_text())
                    path.rename(requests / f".{request['request_id']}.claimed")
                    receipt = {**request, "result": result, "error": None, "steps": []}
                    (receipts / path.name).write_text(json.dumps(receipt))
                    return request
            await asyncio.sleep(0.01)


async def test_runtime_control_needs_a_quiet_node_and_records_the_receipt(
    client: dict[str, Any],
) -> None:
    http = client["http"]
    body = {"operator": "ops", "reason": "maintenance window"}
    serving = await http.post("/v1/maintenance/runtime/restart", json=body, headers=CONTROL)
    assert serving.status_code == 409 and serving.json()["refused"] == "node_not_quiescent"

    await hold(client["dsn"], True)
    await until_gate(client, "maintenance")
    answering = asyncio.create_task(answer(client["supervisor"]))
    done = await http.post("/v1/maintenance/runtime/restart", json=body, headers=CONTROL)
    request = await answering

    assert done.status_code == 200, done.text
    assert done.json()["result"] == "ok"
    assert request["action"] == "restart" and request["reason"] == "ops: maintenance window"
    receipt = await http.get(
        f"/v1/maintenance/runtime/receipts/{request['request_id']}", headers=CONTROL
    )
    assert receipt.json()["request_id"] == request["request_id"]
    events = [
        r["event"]
        for r in await client["agent"].pool.fetch(
            "SELECT event FROM node_operation_audit "
            "WHERE event LIKE 'runtime_control_%' ORDER BY id"
        )
    ]
    assert events == ["runtime_control_requested", "runtime_control_receipt"]


async def test_an_unknown_runtime_action_does_not_exist(client: dict[str, Any]) -> None:
    await hold(client["dsn"], True)
    await until_gate(client, "maintenance")
    response = await client["http"].post(
        "/v1/maintenance/runtime/exec", json={"operator": "o", "reason": "r"}, headers=CONTROL
    )
    assert response.status_code == 404


async def test_an_entry_waits_for_a_promotion_that_is_reading_the_hold(
    database_url: str,
) -> None:
    """The fence: a promotion holds the lock shared while it reads the hold
    and commits; the entry takes it exclusive, so it lands after that commit,
    and every promotion after the entry reads the platform closed."""
    promotion = await asyncpg.connect(_dsn(database_url))
    engine = create_async_engine(database_url)
    try:
        transaction = promotion.transaction()
        await transaction.start()
        await promotion.execute("SELECT pg_advisory_xact_lock_shared($1, $2)", *FENCE_LOCK)
        assert not await promotion.fetchval(
            "SELECT admission_closed FROM maintenance_control WHERE id = 1"
        )

        async def enter() -> bool:
            async with async_sessionmaker(engine)() as session:
                state = await PostgresMaintenanceRepository(session).close(
                    changed_by="admin", message=None, expected_return_at=None
                )
                await session.commit()
                return state is not None and state.admission_closed

        entry = asyncio.create_task(enter())
        await asyncio.sleep(0.3)
        assert not entry.done(), "the entry must wait for the promotion's commit"

        await transaction.commit()
        assert await asyncio.wait_for(entry, 5)
        async with promotion.transaction():
            await promotion.execute("SELECT pg_advisory_xact_lock_shared($1, $2)", *FENCE_LOCK)
            assert await promotion.fetchval(
                "SELECT admission_closed FROM maintenance_control WHERE id = 1"
            )
    finally:
        await promotion.close()
        await engine.dispose()
