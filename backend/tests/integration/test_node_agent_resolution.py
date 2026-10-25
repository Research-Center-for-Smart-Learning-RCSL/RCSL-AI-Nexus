"""Clearing a node block with ordered reset evidence (design S1, T1, U1 on #24).

The witness is simulated by a task that answers challenges the way
`scripts/host/runtime_witness.py` does: it reads the challenge first, then
reports the runtime instance it is told is current.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.availability import read_availability
from app.node_agent.dispatch import Dispatcher, GateState
from app.node_agent.election import claim
from app.node_agent.lock_domain import HostLock, initialise
from app.node_agent.resolution import (
    ATTESTATION_FILE,
    CHALLENGE_FILE,
    ResolutionRefused,
    Resolutions,
    Witness,
)
from app.node_agent.store import OperationStore

NODE = "22222222-2222-2222-2222-222222222222"
ENDPOINT = "127.0.0.1:11434"


class FakeWitness:
    """Answers challenges with whatever runtime instance is current."""

    def __init__(self, out: Path, challenge: Path) -> None:
        self.out, self.challenge = out, challenge
        self.instance = (100, "Thu Oct  8 10:00:00 2026")
        self.incarnation = "w1"
        self.seq = 0
        self.answering = True

    def publish(self, nonce: str | None) -> None:
        self.seq += 1
        document: dict[str, Any] = {
            "nonce": nonce,
            "witness_incarnation": self.incarnation,
            "seq": self.seq,
            "endpoint": ENDPOINT,
            "status": "observed",
            "pid": self.instance[0],
            "start_time": self.instance[1],
        }
        staging = self.out / ".tmp"
        staging.write_text(json.dumps(document))
        os.replace(staging, self.out / ATTESTATION_FILE)

    async def run(self) -> None:
        while True:
            if self.answering:
                try:
                    nonce = (self.challenge / CHALLENGE_FILE).read_text().strip()
                except OSError:
                    nonce = None
                self.publish(nonce)
            await asyncio.sleep(0.02)


@pytest.fixture
async def agent(
    database_url: str, tmp_path: Path, request: pytest.FixtureRequest
) -> AsyncIterator[dict[str, Any]]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    setup = await asyncpg.connect(dsn)
    await setup.execute(
        "INSERT INTO nodes (id, name, address, status, total_memory_gb, runtimes) "
        "VALUES ($1, 'node-r', '100.64.0.2', 'online', 64, '[\"ollama\"]')",
        NODE,
    )
    await setup.close()
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=6)
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    initialise(lock_dir)

    # Agent A sends an operation and dies: the runtime may have it.
    lock_a = HostLock.acquire(lock_dir)
    conn_a = await asyncpg.connect(dsn)
    a = await claim(conn_a, NODE, lock_a, kernel_boot_id="k")
    store_a = OperationStore(pool, a.ownership)
    await store_a.insert_accepted(
        "orphan",
        getattr(request, "param", "inference"),
        request_id=None,
        payload_hash=None,
        store_output=False,
    )
    assert await store_a.promote("orphan", {})
    await conn_a.close()
    lock_a._close_for_tests()  # noqa: SLF001

    # Agent B takes over; the orphan is unknown and the node is blocked.
    lock_b = HostLock.acquire(lock_dir)
    conn_b = await asyncpg.connect(dsn)
    b = await claim(conn_b, NODE, lock_b, kernel_boot_id="k")
    store = OperationStore(pool, b.ownership)
    dispatcher = Dispatcher(store)
    assert await dispatcher.reopen() is GateState.BLOCKED

    out, challenge = tmp_path / "out", tmp_path / "challenge"
    out.mkdir()
    challenge.mkdir()
    fake = FakeWitness(out, challenge)
    producer = asyncio.create_task(fake.run())
    witness = Witness(out, challenge, expected_endpoint=ENDPOINT, timeout_s=1.0, poll_s=0.01)
    try:
        yield {
            "store": store,
            "dispatcher": dispatcher,
            "resolutions": Resolutions(dispatcher, store, witness),
            "witness": fake,
            "pool": pool,
        }
    finally:
        producer.cancel()
        await conn_b.close()
        lock_b._close_for_tests()  # noqa: SLF001
        await pool.close()


@pytest.mark.parametrize("agent", ["inference", "load", "unload", "pull"], indirect=True)
async def test_a_restart_after_the_baseline_clears_the_block(
    agent: dict[str, Any], database_url: str
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            assert (await read_availability(session, {})).unresolved == {NODE: 1}
    finally:
        await engine.dispose()
    started = await agent["resolutions"].start(
        "orphan", evidence="runtime restarted by operator", operator="ops"
    )
    agent["witness"].instance = (200, "Thu Oct  8 10:05:00 2026")  # the restart

    done = await agent["resolutions"].complete(started["resolution_id"])

    assert done == {"op_id": "orphan", "state": "failed", "gate": "serving"}
    op = await agent["store"].observe("orphan")
    assert op is not None and op.state == "failed"
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            assert (await read_availability(session, {})).unresolved == {NODE: 0}
    finally:
        await engine.dispose()
    events = [
        r["event"]
        for r in await agent["pool"].fetch(
            "SELECT event FROM node_operation_audit WHERE op_id = 'orphan' ORDER BY id"
        )
    ]
    assert events == ["resolution_baseline", "resolved_by_reset"]


@pytest.mark.parametrize("agent", ["inference", "load", "unload", "pull"], indirect=True)
async def test_a_restart_that_happened_before_the_baseline_does_not_count(
    agent: dict[str, Any],
) -> None:
    """The review's T1 case: the runtime restarted (R0 to R1) before the
    resolver took the lock, a stale R0 document and an unchallenged R1
    publication both exist. The baseline is the challenged R1, and only a
    restart after it clears the block."""
    witness = agent["witness"]
    witness.answering = False
    witness.instance = (100, "R0")
    witness.publish(None)  # stale, unchallenged
    witness.instance = (150, "R1")  # restarted before quiescence
    witness.publish(None)  # fresh but unchallenged
    witness.answering = True

    started = await agent["resolutions"].start("orphan", evidence="restart", operator="ops")
    assert started["baseline"]["pid"] == 150, "the baseline answers our nonce"

    with pytest.raises(ResolutionRefused, match="has not restarted"):
        await agent["resolutions"].complete(started["resolution_id"])
    op = await agent["store"].observe("orphan")
    assert op is not None and op.state == "outcome_unknown"

    witness.instance = (300, "R2")
    done = await agent["resolutions"].complete(started["resolution_id"])
    assert done["state"] == "failed"


async def test_a_witness_restart_between_observations_starts_over(agent: dict[str, Any]) -> None:
    started = await agent["resolutions"].start("orphan", evidence="restart", operator="ops")
    agent["witness"].incarnation = "w2"
    agent["witness"].instance = (200, "later")

    with pytest.raises(ResolutionRefused, match="witness restarted"):
        await agent["resolutions"].complete(started["resolution_id"])
    with pytest.raises(ResolutionRefused, match="no resolution"):
        await agent["resolutions"].complete(started["resolution_id"])


async def test_without_a_witness_answer_nothing_is_cleared(agent: dict[str, Any]) -> None:
    agent["witness"].answering = False

    with pytest.raises(ResolutionRefused, match="did not answer"):
        await agent["resolutions"].start("orphan", evidence="restart", operator="ops")
    assert agent["dispatcher"].state is not GateState.SERVING


async def test_a_resolution_needs_an_operator_and_a_statement(agent: dict[str, Any]) -> None:
    with pytest.raises(ResolutionRefused, match="operator"):
        await agent["resolutions"].start("orphan", evidence=" ", operator="ops")


class FakeSupervisor:
    """The host supervisor's restart, as the witness then observes it."""

    def __init__(self, witness: FakeWitness, *, result: str = "ok") -> None:
        self.witness = witness
        self.result = result
        self.actions: list[str] = []

    async def run(self, action: str, reason: str) -> dict[str, Any]:
        self.actions.append(action)
        if self.result == "ok":
            self.witness.instance = (400, "Thu Oct  8 11:00:00 2026")
        return {
            "request_id": "a" * 32,
            "action": action,
            "result": self.result,
            "error": None if self.result == "ok" else "runtime processes survived the stop: [812]",
            "before": [{"pid": 100}],
            "after": [{"pid": 400}] if self.result == "ok" else [{"pid": 812}],
        }


async def test_a_supervised_reset_clears_the_block_with_the_receipt_as_evidence(
    agent: dict[str, Any],
) -> None:
    """#49 §5: the same ordered evidence, with the supervisor restarting the
    runtime between the two witness answers instead of an operator."""
    supervisor = FakeSupervisor(agent["witness"])

    done = await agent["resolutions"].reset(
        "orphan", evidence="maintenance reset", operator="ops", supervisor=supervisor
    )

    assert done["state"] == "failed"
    assert supervisor.actions == ["restart"]
    row = await agent["pool"].fetchrow(
        "SELECT detail FROM node_operation_audit "
        "WHERE op_id = 'orphan' AND event = 'resolved_by_reset'"
    )
    evidence = json.loads(row["detail"])
    assert evidence["supervisor_receipt"]["result"] == "ok"
    assert evidence["baseline"]["pid"] == 100 and evidence["after"]["pid"] == 400
    events = [
        r["event"]
        for r in await agent["pool"].fetch(
            "SELECT event FROM node_operation_audit WHERE op_id = 'orphan' ORDER BY id"
        )
    ]
    assert events == ["resolution_baseline", "resolution_restart", "resolved_by_reset"]


async def test_a_failed_supervised_restart_keeps_the_block(agent: dict[str, Any]) -> None:
    supervisor = FakeSupervisor(agent["witness"], result="failed")

    with pytest.raises(ResolutionRefused, match="could not restart"):
        await agent["resolutions"].reset(
            "orphan", evidence="maintenance reset", operator="ops", supervisor=supervisor
        )

    op = await agent["store"].observe("orphan")
    assert op is not None and op.state == "outcome_unknown"
    assert agent["dispatcher"].state is not GateState.SERVING


# -- the maintenance reset (P4 on #61) ----------------------------------------


def _supervisor(tmp_path: Path, *, timeout_s: float = 2.0) -> Any:
    from app.node_agent.supervisor import Supervisor

    requests, receipts = tmp_path / "sv-requests", tmp_path / "sv-receipts"
    requests.mkdir(exist_ok=True)
    receipts.mkdir(exist_ok=True)
    return Supervisor(requests, receipts, timeout_s=timeout_s, poll_s=0.01)


async def _restarting_supervisor(
    tmp_path: Path, witness: FakeWitness, *, answers: int = 1
) -> list[str]:
    """The host supervisor: claim each request, restart (a new runtime
    instance the witness then reports), write the receipt."""
    requests, receipts = tmp_path / "sv-requests", tmp_path / "sv-receipts"
    seen: list[str] = []
    while len(seen) < answers:
        for path in list(requests.iterdir()):
            if path.name.endswith(".json"):
                request = json.loads(path.read_text())
                path.rename(requests / f".{request['request_id']}.claimed")
                witness.instance = (witness.instance[0] + 100, f"restart {len(seen)}")
                receipt = {**request, "result": "ok", "error": None, "steps": []}
                (receipts / path.name).write_text(json.dumps(receipt))
                seen.append(request["request_id"])
        await asyncio.sleep(0.01)
    return seen


async def _close_hold(pool: asyncpg.Pool, epoch: int) -> None:
    await pool.execute(
        "UPDATE maintenance_control SET admission_closed = true, phase = 'maintenance', "
        "epoch = $1 WHERE id = 1",
        epoch,
    )


async def _events(pool: asyncpg.Pool, event: str) -> int:
    count: int = await pool.fetchval(
        "SELECT count(*) FROM node_operation_audit WHERE event = $1", event
    )
    return count


async def test_a_maintenance_reset_resolves_the_unknowns_and_does_not_reopen(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    supervisor = _supervisor(tmp_path)
    await _close_hold(agent["pool"], 7)
    await agent["dispatcher"].freeze(7)
    answering = asyncio.create_task(_restarting_supervisor(tmp_path, agent["witness"]))
    reset_id = "a" * 32

    report = await agent["resolutions"].maintenance_reset(
        epoch=7,
        reset_id=reset_id,
        operator="maintenance coordinator",
        supervisor=supervisor,
        settle_s=2,
        retry_s=0.05,
    )
    await answering

    assert report["accounting"] == "resolved"
    assert report["resolved"] == ["orphan"] and report["remaining_unknown"] == []
    assert report["baseline"]["pid"] != report["after"]["pid"]
    orphan = await agent["store"].observe("orphan")
    assert orphan is not None and orphan.state == "failed"
    assert agent["dispatcher"].state is GateState.MAINTENANCE, "frozen, not reopened"

    again = await agent["resolutions"].maintenance_reset(
        epoch=7,
        reset_id=reset_id,
        operator="maintenance coordinator",
        supervisor=supervisor,
        settle_s=2,
        retry_s=0.05,
    )
    assert again == report
    assert await _events(agent["pool"], "maintenance_reset_receipt") == 1, "one restart"


async def test_without_a_witness_the_runtime_is_released_and_the_unknown_kept(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    supervisor = _supervisor(tmp_path)
    agent["witness"].answering = False
    await _close_hold(agent["pool"], 7)
    await agent["dispatcher"].freeze(7)
    answering = asyncio.create_task(_restarting_supervisor(tmp_path, agent["witness"]))

    report = await agent["resolutions"].maintenance_reset(
        epoch=7,
        reset_id="b" * 32,
        operator="c",
        supervisor=supervisor,
        settle_s=0.2,
        retry_s=0.05,
    )
    await answering

    assert report["supervisor_receipt"]["result"] == "ok"
    assert report["accounting"] == "unresolved"
    assert report["remaining_unknown"] == ["orphan"]
    assert "witness" in (report["accounting_error"] or "")
    orphan = await agent["store"].observe("orphan")
    assert orphan is not None and orphan.state == "outcome_unknown"


async def test_a_reset_resumes_from_its_recorded_baseline_after_an_agent_restart(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    """The first call recorded its baseline and then lost the supervisor; a
    later agent asked again with the same id restarts once, against that
    baseline, rather than taking a new one."""
    from app.node_agent.supervisor import SupervisorRefused

    await _close_hold(agent["pool"], 7)
    await agent["dispatcher"].freeze(7)
    reset_id = "c" * 32
    with pytest.raises(SupervisorRefused):
        await agent["resolutions"].maintenance_reset(
            epoch=7,
            reset_id=reset_id,
            operator="c",
            supervisor=_supervisor(tmp_path, timeout_s=0.1),
            settle_s=1,
            retry_s=0.05,
        )
    assert await _events(agent["pool"], "maintenance_reset_baseline") == 1

    restarted = Resolutions(agent["dispatcher"], agent["store"], agent["resolutions"]._witness)
    answering = asyncio.create_task(_restarting_supervisor(tmp_path, agent["witness"]))
    report = await restarted.maintenance_reset(
        epoch=7,
        reset_id=reset_id,
        operator="c",
        supervisor=_supervisor(tmp_path),
        settle_s=2,
        retry_s=0.05,
    )
    assert await answering == [reset_id]

    assert report["accounting"] == "resolved"
    assert await _events(agent["pool"], "maintenance_reset_baseline") == 1


async def test_a_reset_for_a_hold_reopened_meanwhile_restarts_nothing(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    supervisor = _supervisor(tmp_path)
    await agent["dispatcher"].freeze(7)  # the hold itself is open

    with pytest.raises(ResolutionRefused, match="no longer closed"):
        await agent["resolutions"].maintenance_reset(
            epoch=7, reset_id="d" * 32, operator="c", supervisor=supervisor
        )
    assert list((tmp_path / "sv-requests").iterdir()) == []


async def test_an_unknown_sent_after_the_baseline_is_not_resolved_by_it(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    """Review of #80: work admitted after a reopen can be unknown by the time
    the restart is attested. The restart says nothing about the runtime it
    reached, so only the baseline's cohort is resolved."""
    supervisor = _supervisor(tmp_path)
    await _close_hold(agent["pool"], 7)
    await agent["dispatcher"].freeze(7)
    store = agent["store"]

    async def later_unknown_then_restart() -> None:
        requests = tmp_path / "sv-requests"
        while not any(p.name.endswith(".json") for p in requests.iterdir()):
            await asyncio.sleep(0.01)
        await agent["pool"].execute(
            "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
            "origin_boot_id, owner_generation, submitted_at) VALUES "
            "($1, 'later', 'inference', 'outcome_unknown', $2, 'a-later-boot', $2, now())",
            NODE,
            store.ownership.generation,
        )
        await _restarting_supervisor(tmp_path, agent["witness"])

    answering = asyncio.create_task(later_unknown_then_restart())
    report = await agent["resolutions"].maintenance_reset(
        epoch=7, reset_id="e" * 32, operator="c", supervisor=supervisor, settle_s=2, retry_s=0.05
    )
    await answering

    assert report["resolved"] == ["orphan"]
    assert report["remaining_unknown"] == ["later"]
    assert report["accounting"] == "unresolved"
    later = await store.observe("later")
    assert later is not None and later.state == "outcome_unknown"


async def test_a_hold_lifted_during_the_reset_resolves_nothing(
    agent: dict[str, Any], tmp_path: Path
) -> None:
    supervisor = _supervisor(tmp_path)
    await _close_hold(agent["pool"], 7)
    await agent["dispatcher"].freeze(7)

    async def reopen_then_restart() -> None:
        requests = tmp_path / "sv-requests"
        while not any(p.name.endswith(".json") for p in requests.iterdir()):
            await asyncio.sleep(0.01)
        await agent["pool"].execute(
            "UPDATE maintenance_control SET admission_closed = false WHERE id = 1"
        )
        await _restarting_supervisor(tmp_path, agent["witness"])

    answering = asyncio.create_task(reopen_then_restart())
    report = await agent["resolutions"].maintenance_reset(
        epoch=7, reset_id="f" * 32, operator="c", supervisor=supervisor, settle_s=2, retry_s=0.05
    )
    await answering

    assert report["resolved"] == [] and report["accounting"] == "unresolved"
    assert "lifted" in (report["accounting_error"] or "")
