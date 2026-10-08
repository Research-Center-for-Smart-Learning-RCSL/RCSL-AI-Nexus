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
async def agent(database_url: str, tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
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
        "orphan", "inference", request_id=None, payload_hash=None, store_output=False
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


async def test_a_restart_after_the_baseline_clears_the_block(agent: dict[str, Any]) -> None:
    started = await agent["resolutions"].start(
        "orphan", evidence="runtime restarted by operator", operator="ops"
    )
    agent["witness"].instance = (200, "Thu Oct  8 10:05:00 2026")  # the restart

    done = await agent["resolutions"].complete(started["resolution_id"])

    assert done == {"op_id": "orphan", "state": "failed", "gate": "serving"}
    op = await agent["store"].observe("orphan")
    assert op is not None and op.state == "failed"
    events = [
        r["event"]
        for r in await agent["pool"].fetch(
            "SELECT event FROM node_operation_audit WHERE op_id = 'orphan' ORDER BY id"
        )
    ]
    assert events == ["resolution_baseline", "resolved_by_reset"]


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
