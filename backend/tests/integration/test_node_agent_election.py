"""Node agent election, takeover and fenced writes on real PostgreSQL.

Final spec §3 on #24 requires these on a real server, including terminating
the election session while the process lives; design revisions R1-R3, S2, S3
and revision 4 define what each test asserts.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from app.node_agent.election import ElectionRefused, claim, still_elected
from app.node_agent.lock_domain import HostLock, initialise
from app.node_agent.store import DISPATCH_NAMESPACE, NotOwner, OperationStore

NODE = "11111111-1111-1111-1111-111111111111"


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture
async def dsn(database_url: str) -> str:
    dsn = _dsn(database_url)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO nodes (id, name, address, status, total_memory_gb, runtimes) "
            "VALUES ($1, 'node-a', '100.64.0.1', 'online', 64, '[\"ollama\"]')",
            NODE,
        )
    finally:
        await conn.close()
    return dsn


@pytest.fixture
async def pool(dsn: str) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()


def _domain(tmp_path: Path, name: str = "lock") -> Path:
    directory = tmp_path / name
    directory.mkdir()
    initialise(directory)
    return directory


async def _elect(dsn: str, directory: Path, kernel: str | None = "k1"):  # type: ignore[no-untyped-def]
    lock = HostLock.acquire(directory)
    conn = await asyncpg.connect(dsn)
    try:
        elected = await claim(conn, NODE, lock, kernel_boot_id=kernel)
    except BaseException:
        await conn.close()
        lock._close_for_tests()  # noqa: SLF001
        raise
    return lock, conn, elected


async def _die(lock: HostLock, conn: asyncpg.Connection) -> None:
    """The process ends: its session and its host lock go with it."""
    await conn.close()
    lock._close_for_tests()  # noqa: SLF001


async def test_one_agent_wins_the_node(dsn: str, tmp_path: Path) -> None:
    directory = _domain(tmp_path)
    lock, conn, elected = await _elect(dsn, directory)
    assert elected.ownership.generation == 1

    # A second claimant on another kernel of the same domain cannot even get
    # the host lock while the first lives.
    with pytest.raises(Exception, match="held by another live process"):
        HostLock.acquire(directory)

    # And a claimant that somehow had a host lock still loses the advisory lock.
    stray = await asyncpg.connect(dsn)
    other = _domain(tmp_path, "other")
    other_lock = HostLock.acquire(other)
    try:
        with pytest.raises(ElectionRefused, match="another agent holds"):
            await claim(stray, NODE, other_lock, kernel_boot_id="k1")
    finally:
        await stray.close()
        other_lock._close_for_tests()  # noqa: SLF001
    await _die(lock, conn)


async def test_a_foreign_lock_domain_is_refused_after_the_owner_is_gone(
    dsn: str, tmp_path: Path
) -> None:
    """Design S2: the node binds the first domain; another volume's lock proves
    nothing about a sender that may still live in the bound one."""
    lock, conn, _ = await _elect(dsn, _domain(tmp_path, "first"))
    await _die(lock, conn)

    with pytest.raises(ElectionRefused, match="bound to lock domain"):
        await _elect(dsn, _domain(tmp_path, "second"))


async def test_takeover_resolves_open_work_conservatively(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    directory = _domain(tmp_path)
    lock, conn, a = await _elect(dsn, directory)
    store = OperationStore(pool, a.ownership)
    await store.insert_accepted(
        "op-run", "inference", request_id=None, payload_hash=None, store_output=False
    )
    await store.insert_accepted(
        "op-acc", "inference", request_id=None, payload_hash=None, store_output=False
    )
    assert await store.promote("op-run", {})
    await _die(lock, conn)

    lock_b, conn_b, b = await _elect(dsn, directory)

    assert b.ownership.generation == a.ownership.generation + 1
    assert (b.converted_unknown, b.converted_unsent) == (1, 1)
    store_b = OperationStore(pool, b.ownership)
    run = await store_b.observe("op-run")
    acc = await store_b.observe("op-acc")
    assert run is not None and run.state == "outcome_unknown"
    assert run.origin_generation == a.ownership.generation, "sender provenance kept"
    assert run.owner_generation == b.ownership.generation
    assert acc is not None and acc.state == "cancelled_unsent"
    assert await store_b.any_unknown()
    await _die(lock_b, conn_b)


async def test_a_superseded_owner_cannot_write_anything(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    """Design R2: A's delayed completion after takeover clears no block and
    publishes no result; it is audited and nothing else."""
    directory = _domain(tmp_path)
    lock, conn, a = await _elect(dsn, directory)
    store_a = OperationStore(pool, a.ownership)
    await store_a.insert_accepted(
        "op", "inference", request_id=None, payload_hash=None, store_output=True
    )
    assert await store_a.promote("op", {})
    await _die(lock, conn)
    lock_b, conn_b, b = await _elect(dsn, directory)

    with pytest.raises(NotOwner):
        await store_a.finish("op", "completed", {"eval_count": 3}, result={"content": "x"})

    store_b = OperationStore(pool, b.ownership)
    op = await store_b.observe("op")
    assert op is not None and op.state == "outcome_unknown"
    assert await store_b.stored_result("op") is None
    events = await pool.fetch(
        "SELECT event, detail FROM node_operation_audit WHERE op_id = 'op' ORDER BY id"
    )
    assert [e["event"] for e in events] == ["stale_completion"]
    assert json.loads(events[0]["detail"])["generation"] == a.ownership.generation
    with pytest.raises(NotOwner):
        await store_a.insert_accepted(
            "new", "inference", request_id=None, payload_hash=None, store_output=False
        )
    stale = await pool.fetch(
        "SELECT event FROM node_operation_audit WHERE op_id = 'new' ORDER BY id"
    )
    assert [e["event"] for e in stale] == ["stale_insert"], "every refused write is audited"
    await _die(lock_b, conn_b)


async def test_a_terminated_election_session_is_a_lost_role_not_a_retake(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    assert await still_elected(conn, a.backend_pid)

    await pool.execute("SELECT pg_terminate_backend($1)", a.backend_pid)

    assert not await still_elected(conn, a.backend_pid)
    # The process lives and keeps its host lock, so no successor on this host
    # can be elected until it exits (design U1: it exits once its admitted
    # work is terminal).
    with pytest.raises(Exception, match="held by another live process"):
        HostLock.acquire(tmp_path / "lock")
    lock._close_for_tests()  # noqa: SLF001


async def test_a_kernel_change_with_work_in_flight_needs_an_operator(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    directory = _domain(tmp_path)
    lock, conn, a = await _elect(dsn, directory, kernel="k1")
    store = OperationStore(pool, a.ownership)
    await store.insert_accepted(
        "op", "inference", request_id=None, payload_hash=None, store_output=False
    )
    assert await store.promote("op", {})
    await _die(lock, conn)

    with pytest.raises(ElectionRefused, match="kernel changed"):
        await _elect(dsn, directory, kernel="k2")


async def test_a_kernel_change_with_nothing_in_flight_is_accepted(dsn: str, tmp_path: Path) -> None:
    directory = _domain(tmp_path)
    lock, conn, _ = await _elect(dsn, directory, kernel="k1")
    await _die(lock, conn)

    lock2, conn2, b = await _elect(dsn, directory, kernel="k2")
    assert b.ownership.generation == 2
    await _die(lock2, conn2)


async def test_promotion_is_claimed_exactly_once(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    store = OperationStore(pool, a.ownership)
    await store.insert_accepted(
        "op", "inference", request_id=None, payload_hash=None, store_output=False
    )

    results = await asyncio.gather(*(store.promote("op", {}) for _ in range(5)))

    assert sorted(results) == [False, False, False, False, True]
    await _die(lock, conn)


async def test_no_promotion_while_any_operation_is_unknown(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    store = OperationStore(pool, a.ownership)
    for op in ("x", "y"):
        await store.insert_accepted(
            op, "inference", request_id=None, payload_hash=None, store_output=False
        )
    assert await store.promote("x", {})
    assert await store.mark_unknown("x", "read_error", {"chunks": 2})

    assert not await store.promote("y", {})
    y = await store.observe("y")
    assert y is not None and y.state == "accepted"
    await _die(lock, conn)


async def test_an_unknown_write_waits_for_an_overlapping_promotion_decision(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    """Design S3, the overlapping two-connection case: a transaction holding
    the dispatch lock mid-decision makes `mark_unknown` wait for its commit,
    so a decision cannot read 'no unknown' while one is being committed."""
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    store = OperationStore(pool, a.ownership)
    await store.insert_accepted(
        "y", "inference", request_id=None, payload_hash=None, store_output=False
    )
    assert await store.promote("y", {})

    deciding = await pool.acquire()
    tx = deciding.transaction()
    await tx.start()
    await deciding.execute(
        "SELECT pg_advisory_xact_lock($1, hashtext($2))", DISPATCH_NAMESPACE, NODE
    )
    assert not await deciding.fetchval(
        "SELECT EXISTS (SELECT 1 FROM node_operations WHERE node_id = $1 "
        "AND state = 'outcome_unknown')",
        NODE,
    )

    writer = asyncio.create_task(store.mark_unknown("y", "read_error", {}))
    await asyncio.sleep(0.3)
    assert not writer.done(), "the unknown transition waited for the decision"

    await tx.commit()
    await pool.release(deciding)
    assert await asyncio.wait_for(writer, 5)
    await _die(lock, conn)


async def test_cancel_tombstones_an_absent_attempt_and_never_rewrites_running(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    store = OperationStore(pool, a.ownership)

    absent = await store.cancel_accepted("late", "rebind")
    assert absent is not None and absent.state == "cancelled_unsent"
    assert (
        await store.insert_accepted(
            "late", "inference", request_id=None, payload_hash=None, store_output=False
        )
        is None
    ), "the late original only observes the tombstone"

    await store.insert_accepted(
        "queued", "inference", request_id=None, payload_hash=None, store_output=False
    )
    queued = await store.cancel_accepted("queued", "rebind")
    assert queued is not None and queued.state == "cancelled_unsent"

    await store.insert_accepted(
        "sent", "inference", request_id=None, payload_hash=None, store_output=False
    )
    assert await store.promote("sent", {})
    sent = await store.cancel_accepted("sent", "rebind")
    assert sent is not None and sent.state == "running"
    await _die(lock, conn)


async def test_completion_commits_the_result_with_the_terminal_state(
    dsn: str, pool: asyncpg.Pool, tmp_path: Path
) -> None:
    lock, conn, a = await _elect(dsn, _domain(tmp_path))
    store = OperationStore(pool, a.ownership)
    op_id = str(uuid.uuid4())
    await store.insert_accepted(
        op_id, "inference", request_id="r", payload_hash="h", store_output=True
    )
    assert await store.promote(op_id, {"manifest": "abc"})

    assert await store.finish(op_id, "completed", {"eval_count": 7}, result={"content": "hi"})

    op = await store.observe(op_id)
    assert op is not None and op.state == "completed" and op.terminal == {"eval_count": 7}
    assert await store.stored_result(op_id) == {"content": "hi"}
    assert not await store.finish(op_id, "failed", {}), "terminal is terminal"
    await _die(lock, conn)
