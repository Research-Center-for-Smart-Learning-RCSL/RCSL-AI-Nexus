"""Becoming the node's agent, and noticing when that stops being true.

Two locks, always in this order (design R1 on #24):

1. The host lock (`lock_domain.HostLock`), proving every earlier sender on
   this host is gone.
2. The node's session advisory lock, on one dedicated connection outside any
   pool, recording its backend PID.

Then one transaction takes over: binds or checks the node's lock domain,
advances the generation, and resolves the previous owner's open work
conservatively. `running` becomes `outcome_unknown` (it may have been sent),
`accepted` becomes `cancelled_unsent` (it provably was not, since `running` is
committed before any byte is sent), and every non-terminal row moves to the
new owner so that only it may write them.

The role is then watched with a plain `SELECT pg_backend_pid()` on the same
connection, never `pg_try_advisory_lock`, which would silently re-acquire. A
failed check or a different PID means the role is lost, for good: the caller
closes its gate and exits once its admitted work is terminal.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import asyncpg

from app.node_agent.lock_domain import HostLock
from app.node_agent.store import (
    DISPATCH_NAMESPACE,
    ELECTION_NAMESPACE,
    LIFECYCLE_KINDS,
    Ownership,
)


class ElectionRefused(Exception):  # noqa: N818 - a refusal, reported as such
    """This process may not become the node's agent; the reason says why."""


@dataclass(frozen=True, slots=True)
class Elected:
    ownership: Ownership
    backend_pid: int
    converted_unknown: int
    converted_unsent: int


async def claim(
    conn: asyncpg.Connection,
    node_id: str,
    host_lock: HostLock,
    *,
    kernel_boot_id: str | None,
) -> Elected:
    """Take the node, or raise `ElectionRefused` having changed nothing.

    `conn` must be a dedicated connection: the session advisory lock lives
    exactly as long as it does.
    """
    if not host_lock.still_held():
        raise ElectionRefused("the host lock is no longer this domain's lock file")
    if not await conn.fetchval(
        "SELECT pg_try_advisory_lock($1, hashtext($2))", ELECTION_NAMESPACE, node_id
    ):
        raise ElectionRefused(f"another agent holds node {node_id}")

    backend_pid: int = await conn.fetchval("SELECT pg_backend_pid()")
    boot_id = str(uuid.uuid4())
    domain_id = host_lock.domain.domain_id
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, hashtext($2))", DISPATCH_NAMESPACE, node_id
            )
            # `node_agents` before `nodes`, and `nodes` only FOR NO KEY UPDATE:
            # a superseded owner's insert holds `node_agents` FOR SHARE and then
            # takes FOR KEY SHARE on `nodes` through its foreign key, so the
            # opposite order could deadlock (review on #33).
            if not await conn.fetchval("SELECT 1 FROM nodes WHERE id = $1", node_id):
                raise ElectionRefused(f"node {node_id} is not registered")
            await conn.execute(
                "INSERT INTO node_agents (node_id) VALUES ($1) ON CONFLICT DO NOTHING", node_id
            )
            previous = await conn.fetchrow(
                "SELECT generation, boot_id, kernel_boot_id FROM node_agents "
                "WHERE node_id = $1 FOR UPDATE",
                node_id,
            )
            if previous is None:  # inserted above, under the same transaction
                raise ElectionRefused(f"node {node_id} has no agent row")
            bound = await conn.fetchrow(
                "SELECT lock_domain_id FROM nodes WHERE id = $1 FOR NO KEY UPDATE", node_id
            )
            if bound is None:
                raise ElectionRefused(f"node {node_id} is not registered")
            if bound["lock_domain_id"] is None:
                await conn.execute(
                    "UPDATE nodes SET lock_domain_id = $2 WHERE id = $1", node_id, domain_id
                )
            elif bound["lock_domain_id"] != domain_id:
                # Design S2: another volume or VM. Its own flock proves nothing
                # about the sender in the bound domain, which may still be alive.
                raise ElectionRefused(
                    f"node {node_id} is bound to lock domain {bound['lock_domain_id']}, "
                    f"not {domain_id}; moving a node between domains is an operator action"
                )

            if (
                previous["kernel_boot_id"] is not None
                and kernel_boot_id != previous["kernel_boot_id"]
            ):
                # Same domain, another kernel: the same VM after a reboot, or a
                # clone. Accepted only when nothing can be in flight, because an
                # old holder whose gate closed sends nothing new (design rev 4).
                open_rows = await conn.fetchval(
                    "SELECT count(*) FROM node_operations WHERE node_id = $1 "
                    "AND state IN ('running', 'outcome_unknown')",
                    node_id,
                )
                if open_rows:
                    raise ElectionRefused(
                        f"the kernel changed since the last owner and node {node_id} has "
                        f"{open_rows} running or unknown operations; an operator must "
                        "establish that the previous kernel is gone"
                    )

            generation: int = previous["generation"] + 1
            await conn.execute(
                "UPDATE node_agents SET generation = $2, boot_id = $3, kernel_boot_id = $4, "
                "election_backend_pid = $5, started_at = now() WHERE node_id = $1",
                node_id,
                generation,
                boot_id,
                kernel_boot_id,
                backend_pid,
            )
            takeover = json.dumps(
                {
                    "takeover_by_generation": generation,
                    "previous_generation": previous["generation"],
                    "previous_boot_id": previous["boot_id"],
                }
            )
            # A lifecycle operation that may have been sent changes residency,
            # not output nobody can account for: it fails, recorded, and does
            # not block (PR4b; final spec §3 blocks on inference, summary and
            # embedding). Residency is observed again by the heartbeat, and a
            # pull that may have rewritten a tag is caught by the weights pin.
            await conn.execute(
                "UPDATE node_operations SET state = 'failed', owner_generation = $2, "
                "reason = 'orphaned_lifecycle', resolved_at = now(), resolved_by = 'takeover', "
                "provenance = provenance || $3::jsonb "
                "WHERE node_id = $1 AND state = 'running' AND kind = ANY($4::text[])",
                node_id,
                generation,
                takeover,
                sorted(LIFECYCLE_KINDS),
            )
            unknown = await conn.fetchval(
                "WITH moved AS (UPDATE node_operations SET state = 'outcome_unknown', "
                "owner_generation = $2, reason = 'orphaned_by_takeover', "
                "provenance = provenance || $3::jsonb "
                "WHERE node_id = $1 AND state = 'running' RETURNING 1) SELECT count(*) FROM moved",
                node_id,
                generation,
                takeover,
            )
            unsent = await conn.fetchval(
                "WITH moved AS (UPDATE node_operations SET state = 'cancelled_unsent', "
                "owner_generation = $2, reason = 'orphaned_by_takeover', resolved_at = now(), "
                "resolved_by = 'takeover', provenance = provenance || $3::jsonb "
                "WHERE node_id = $1 AND state = 'accepted' RETURNING 1) "
                "SELECT count(*) FROM moved",
                node_id,
                generation,
                takeover,
            )
            await conn.execute(
                "UPDATE node_operations SET owner_generation = $2 "
                "WHERE node_id = $1 AND state = 'outcome_unknown'",
                node_id,
                generation,
            )
            await conn.execute(
                "INSERT INTO node_operation_audit (node_id, op_id, event, detail) "
                "VALUES ($1, NULL, 'takeover', $2::jsonb)",
                node_id,
                json.dumps(
                    {
                        "generation": generation,
                        "boot_id": boot_id,
                        "kernel_boot_id": kernel_boot_id,
                        "domain_id": domain_id,
                        "previous_generation": previous["generation"],
                        "previous_boot_id": previous["boot_id"],
                        "previous_kernel_boot_id": previous["kernel_boot_id"],
                        "converted_unknown": unknown,
                        "converted_unsent": unsent,
                    }
                ),
            )
    except BaseException:
        await conn.execute(
            "SELECT pg_advisory_unlock($1, hashtext($2))", ELECTION_NAMESPACE, node_id
        )
        raise

    return Elected(
        ownership=Ownership(node_id=node_id, generation=generation, boot_id=boot_id),
        backend_pid=backend_pid,
        converted_unknown=unknown,
        converted_unsent=unsent,
    )


async def still_elected(conn: asyncpg.Connection, backend_pid: int) -> bool:
    """Whether the election session is the one that won.

    A plain PID read on that connection: a terminated session raises, a
    reconnected one has another PID. Neither is ever repaired by retaking the
    lock, because the work admitted under the old session is not re-fenced.
    """
    try:
        current = await conn.fetchval("SELECT pg_backend_pid()")
    except Exception:  # noqa: BLE001 - any failure of the check is a lost role
        # A terminated session surfaces as a server error, a closed socket or
        # asyncpg's InternalClientError, depending on timing; all mean the
        # same thing here, and guessing wrong in the other direction would
        # keep dispatching without the role.
        return False
    return isinstance(current, int) and current == backend_pid
