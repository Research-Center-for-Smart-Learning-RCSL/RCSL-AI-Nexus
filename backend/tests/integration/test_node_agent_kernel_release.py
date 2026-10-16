"""Releasing a node from its previous kernel on real PostgreSQL (#62, item 5).

Election refuses a new kernel while work may be in flight (design revision 4).
The release records the operator's statement that the previous kernel is gone
and nothing else: the open operations stay open, takeover makes them unknown,
and only the existing reset-evidence resolution makes them terminal.
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg
import pytest

from app.node_agent.dispatch import Dispatcher, GateState
from app.node_agent.election import ElectionRefused, claim
from app.node_agent.lock_domain import HostLock, initialise
from app.node_agent.release_kernel import ReleaseRefused, release_previous_kernel
from app.node_agent.store import ELECTION_NAMESPACE, OperationStore

NODE = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
async def dsn(database_url: str) -> str:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO nodes (id, name, address, status, total_memory_gb, runtimes) "
            "VALUES ($1, 'node-k', '100.64.0.3', 'online', 64, '[\"ollama\"]')",
            NODE,
        )
    finally:
        await conn.close()
    return dsn


def _domain(tmp_path: Path, name: str = "lock") -> Path:
    directory = tmp_path / name
    directory.mkdir()
    initialise(directory)
    return directory


async def _orphan_in_kernel_one(dsn: str, directory: Path, kind: str = "load") -> None:
    """An agent in kernel k1 sends an operation, and the VM goes away."""
    lock = HostLock.acquire(directory)
    conn = await asyncpg.connect(dsn)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        elected = await claim(conn, NODE, lock, kernel_boot_id="k1")
        store = OperationStore(pool, elected.ownership)
        await store.insert_accepted(
            "orphan", kind, request_id=None, payload_hash=None, store_output=False
        )
        assert await store.promote("orphan", {})
    finally:
        await pool.close()
        await conn.close()
        lock._close_for_tests()  # noqa: SLF001


async def _release(dsn: str, lock: HostLock, **overrides: str) -> dict[str, object]:
    arguments = {
        "previous_kernel_boot_id": "k1",
        "current_kernel_boot_id": "k2",
        "operator": "ops",
        "reason": "colima restarted; only one VM exists",
    }
    arguments.update(overrides)
    conn = await asyncpg.connect(dsn)
    try:
        return await release_previous_kernel(conn, NODE, lock, **arguments)
    finally:
        await conn.close()


async def _kernel(dsn: str) -> str | None:
    conn = await asyncpg.connect(dsn)
    try:
        value: str | None = await conn.fetchval(
            "SELECT kernel_boot_id FROM node_agents WHERE node_id = $1", NODE
        )
        return value
    finally:
        await conn.close()


async def test_a_release_lets_the_agent_in_and_leaves_resolution_to_reset_evidence(
    dsn: str, tmp_path: Path
) -> None:
    directory = _domain(tmp_path)
    await _orphan_in_kernel_one(dsn, directory)

    # The new kernel's agent is refused, as before.
    lock = HostLock.acquire(directory)
    conn = await asyncpg.connect(dsn)
    with pytest.raises(ElectionRefused, match="kernel changed"):
        await claim(conn, NODE, lock, kernel_boot_id="k2")

    released = await _release(dsn, lock)
    assert released["operations"] == [
        {"op_id": "orphan", "kind": "load", "state": "running", "origin_generation": 1}
    ]

    # The same process stands in for the restarted agent: it already holds
    # the host lock, as the agent will once the CLI has exited.
    elected = await claim(conn, NODE, lock, kernel_boot_id="k2")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        assert elected.converted_unknown == 1
        store = OperationStore(pool, elected.ownership)
        op = await store.observe("orphan")
        assert op is not None and op.state == "outcome_unknown"
        assert await Dispatcher(store).reopen() is GateState.BLOCKED

        audit = await pool.fetchrow(
            "SELECT op_id, detail FROM node_operation_audit "
            "WHERE node_id = $1 AND event = 'kernel_released'",
            NODE,
        )
        assert audit is not None and audit["op_id"] is None
        detail = json.loads(audit["detail"])
        assert detail["operator"] == "ops"
        assert detail["previous_kernel_boot_id"] == "k1"
        assert detail["current_kernel_boot_id"] == "k2"
        assert [o["op_id"] for o in detail["operations"]] == ["orphan"]

        # Terminal only through the existing reset-evidence transition.
        assert await store.resolve_unknown("orphan", {"operator": "ops"})
        op = await store.observe("orphan")
        assert op is not None and op.state == "failed" and op.reason == "resolved_by_reset"
    finally:
        await pool.close()
        await conn.close()
        lock._close_for_tests()  # noqa: SLF001


async def test_a_wrong_previous_kernel_changes_nothing(dsn: str, tmp_path: Path) -> None:
    directory = _domain(tmp_path)
    await _orphan_in_kernel_one(dsn, directory)
    lock = HostLock.acquire(directory)
    try:
        with pytest.raises(ReleaseRefused, match="ran in kernel k1, not k0"):
            await _release(dsn, lock, previous_kernel_boot_id="k0")
        assert await _kernel(dsn) == "k1"
    finally:
        lock._close_for_tests()  # noqa: SLF001


async def test_a_release_is_refused_while_an_agent_holds_the_node(dsn: str, tmp_path: Path) -> None:
    directory = _domain(tmp_path)
    await _orphan_in_kernel_one(dsn, directory)
    # An agent elsewhere (another kernel or domain) holds the election lock
    # while this domain's host lock is free: the database lock alone refuses.
    holder = await asyncpg.connect(dsn)
    lock = HostLock.acquire(directory)
    try:
        await holder.execute("SELECT pg_advisory_lock($1, hashtext($2))", ELECTION_NAMESPACE, NODE)
        with pytest.raises(ReleaseRefused, match="an agent holds node"):
            await _release(dsn, lock)
        assert await _kernel(dsn) == "k1"
    finally:
        await holder.close()
        lock._close_for_tests()  # noqa: SLF001


async def test_a_release_with_nothing_open_is_refused(dsn: str, tmp_path: Path) -> None:
    directory = _domain(tmp_path)
    lock = HostLock.acquire(directory)
    conn = await asyncpg.connect(dsn)
    await claim(conn, NODE, lock, kernel_boot_id="k1")
    await conn.close()
    lock._close_for_tests()  # noqa: SLF001

    lock = HostLock.acquire(directory)
    try:
        with pytest.raises(ReleaseRefused, match="no running or unknown operations"):
            await _release(dsn, lock)
        assert await _kernel(dsn) == "k1"
    finally:
        lock._close_for_tests()  # noqa: SLF001


async def test_a_release_from_another_lock_domain_is_refused(dsn: str, tmp_path: Path) -> None:
    await _orphan_in_kernel_one(dsn, _domain(tmp_path))
    lock = HostLock.acquire(_domain(tmp_path, "clone"))
    try:
        with pytest.raises(ReleaseRefused, match="is bound to lock domain"):
            await _release(dsn, lock)
        assert await _kernel(dsn) == "k1"
    finally:
        lock._close_for_tests()  # noqa: SLF001
