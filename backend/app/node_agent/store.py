"""Durable operations, written only by the node's current owner.

Every write the agent makes about an operation happens in a transaction that
first proves this process still owns the node (design R2 on #24): it reads
`node_agents` `FOR SHARE` and requires the generation and boot id it was
elected with, and the row it updates must carry `owner_generation` equal to
that generation and the expected source state. Takeover locks `node_agents`
`FOR UPDATE`, so the two serialise, and a write from a superseded owner
matches nothing; it is recorded in the audit trail and published nowhere.

The dispatch decision and every transition into `outcome_unknown` take one
more, conflicting lock first: the per-node transaction advisory lock (design
S3). `FOR SHARE` locks are compatible with each other, so without it a
promotion could read "no unknown" while another transaction commits one.

Lock order, everywhere: the dispatch lock, then `node_agents`, then operation
rows. No network I/O happens inside any of these transactions.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg

ELECTION_NAMESPACE = 0x4E58_0001
"""First key of the session advisory lock that elects the node's agent."""

DISPATCH_NAMESPACE = 0x4E58_0002
"""First key of the transaction advisory lock that orders dispatch decisions."""


class NotOwner(Exception):  # noqa: N818 - a state, not a failure
    """This process no longer owns the node; its write was not applied."""


@dataclass(frozen=True, slots=True)
class Ownership:
    node_id: str
    generation: int
    boot_id: str


@dataclass(frozen=True, slots=True)
class Operation:
    node_id: str
    op_id: str
    kind: str
    state: str
    origin_generation: int
    origin_boot_id: str
    owner_generation: int
    request_id: str | None
    payload_hash: str | None
    store_output: bool
    reason: str | None
    terminal: dict[str, Any] | None
    replay_unavailable: bool


def _operation(row: asyncpg.Record) -> Operation:
    terminal = row["terminal"]
    return Operation(
        node_id=row["node_id"],
        op_id=row["op_id"],
        kind=row["kind"],
        state=row["state"],
        origin_generation=row["origin_generation"],
        origin_boot_id=row["origin_boot_id"],
        owner_generation=row["owner_generation"],
        request_id=row["request_id"],
        payload_hash=row["payload_hash"],
        store_output=row["store_output"],
        reason=row["reason"],
        terminal=json.loads(terminal) if isinstance(terminal, str) else terminal,  # JSONB text
        replay_unavailable=row["replay_unavailable"],
    )


_SELECT_OPERATION = (
    "SELECT node_id, op_id, kind, state, origin_generation, origin_boot_id, owner_generation, "
    "request_id, payload_hash, store_output, reason, terminal, replay_unavailable "
    "FROM node_operations WHERE node_id = $1 AND op_id = $2"
)


class OperationStore:
    def __init__(self, pool: asyncpg.Pool, ownership: Ownership) -> None:
        self._pool = pool
        self.ownership = ownership

    @property
    def node_id(self) -> str:
        return self.ownership.node_id

    # -- transactions ------------------------------------------------------

    async def _prove_ownership(self, conn: asyncpg.Connection) -> None:
        row = await conn.fetchrow(
            "SELECT generation, boot_id FROM node_agents WHERE node_id = $1 FOR SHARE",
            self.node_id,
        )
        if (
            row is None
            or row["generation"] != self.ownership.generation
            or row["boot_id"] != self.ownership.boot_id
        ):
            raise NotOwner(
                f"node {self.node_id} is owned by generation "
                f"{row['generation'] if row else None}, not {self.ownership.generation}"
            )

    @asynccontextmanager
    async def _owned(
        self, *, dispatch: bool, action: str, op_id: str | None = None
    ) -> AsyncIterator[asyncpg.Connection]:
        """A transaction that proves ownership first; a refused write is audited.

        Every refusal is evidence of a superseded owner still trying to act
        (design R2), so it is recorded whichever write it was, then raised so
        the caller closes its gate (review on #33).
        """
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                if dispatch:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock($1, hashtext($2))",
                        DISPATCH_NAMESPACE,
                        self.node_id,
                    )
                await self._prove_ownership(conn)
                yield conn
        except NotOwner as exc:
            await self.audit(
                f"stale_{action}",
                op_id,
                {
                    "generation": self.ownership.generation,
                    "boot_id": self.ownership.boot_id,
                    "error": str(exc),
                },
            )
            raise

    # -- reads -------------------------------------------------------------

    async def observe(self, op_id: str) -> Operation | None:
        row = await self._pool.fetchrow(
            _SELECT_OPERATION,
            self.node_id,
            op_id,
        )
        return _operation(row) if row else None

    async def stored_result(self, op_id: str) -> dict[str, Any] | None:
        value = await self._pool.fetchval(
            "SELECT result FROM attempt_results WHERE node_id = $1 AND op_id = $2",
            self.node_id,
            op_id,
        )
        if value is None:
            return None
        decoded = json.loads(value) if isinstance(value, str) else value
        if not isinstance(decoded, dict):
            raise TypeError(f"stored result for {op_id} is not an object")
        return decoded

    async def any_unknown(self) -> bool:
        return bool(
            await self._pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM node_operations "
                "WHERE node_id = $1 AND state = 'outcome_unknown')",
                self.node_id,
            )
        )

    # -- writes ------------------------------------------------------------

    async def insert_accepted(
        self,
        op_id: str,
        kind: str,
        *,
        request_id: str | None,
        payload_hash: str | None,
        store_output: bool,
    ) -> Operation | None:
        """The new `accepted` row, or None when the op id already exists.

        A loser of the race only observes the existing attempt; reading
        `accepted` grants nothing (design R3).
        """
        async with self._owned(dispatch=False, action="insert", op_id=op_id) as conn:
            row = await conn.fetchrow(
                "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
                "origin_boot_id, owner_generation, request_id, payload_hash, store_output) "
                "VALUES ($1, $2, $3, 'accepted', $4, $5, $4, $6, $7, $8) "
                "ON CONFLICT (node_id, op_id) DO NOTHING RETURNING node_id, op_id, kind, state, "
                "origin_generation, origin_boot_id, owner_generation, request_id, payload_hash, "
                "store_output, reason, terminal, replay_unavailable",
                self.node_id,
                op_id,
                kind,
                self.ownership.generation,
                self.ownership.boot_id,
                request_id,
                payload_hash,
                store_output,
            )
        return _operation(row) if row else None

    async def promote(self, op_id: str, provenance: dict[str, Any]) -> bool:
        """Claim `accepted → running`: the authorisation point for a send.

        True for exactly one caller, and only while no operation on the node is
        unknown. The in-process gate is checked by the caller, under the barrier
        that block, drain and role loss also take (design S3, T2).
        """
        async with self._owned(dispatch=True, action="promotion", op_id=op_id) as conn:
            if await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM node_operations "
                "WHERE node_id = $1 AND state = 'outcome_unknown')",
                self.node_id,
            ):
                return False
            claimed = await conn.fetchval(
                "UPDATE node_operations SET state = 'running', running_at = now(), "
                "provenance = provenance || $4::jsonb "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'accepted' "
                "AND owner_generation = $3 RETURNING op_id",
                self.node_id,
                op_id,
                self.ownership.generation,
                json.dumps(provenance),
            )
        return claimed is not None

    async def cancel_accepted(self, op_id: str, reason: str) -> Operation | None:
        """Make an absent or `accepted` attempt `cancelled_unsent`.

        Inserts a tombstone when the op id is unknown here, so a late original
        POST conflicts with it and only observes it (design S6). Never rewrites
        `running`, unknown or terminal work: those are returned unchanged.
        """
        async with self._owned(dispatch=True, action="cancel", op_id=op_id) as conn:
            await conn.execute(
                "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
                "origin_boot_id, owner_generation, reason, resolved_at, resolved_by) "
                "VALUES ($1, $2, 'inference', 'cancelled_unsent', $3, $4, $3, $5, now(), "
                "'cancel') "
                "ON CONFLICT (node_id, op_id) DO UPDATE SET state = 'cancelled_unsent', "
                "reason = EXCLUDED.reason, resolved_at = now(), resolved_by = 'cancel' "
                "WHERE node_operations.state = 'accepted' "
                "AND node_operations.owner_generation = EXCLUDED.owner_generation",
                self.node_id,
                op_id,
                self.ownership.generation,
                self.ownership.boot_id,
                reason,
            )
            row = await conn.fetchrow(
                _SELECT_OPERATION,
                self.node_id,
                op_id,
            )
        return _operation(row) if row else None

    async def mark_unknown(self, op_id: str, reason: str, observed: dict[str, Any]) -> bool:
        """`running → outcome_unknown`, under the dispatch lock (design S3)."""
        async with self._owned(dispatch=True, action="unknown", op_id=op_id) as conn:
            done = await conn.fetchval(
                "UPDATE node_operations SET state = 'outcome_unknown', reason = $4, "
                "observed = $5::jsonb "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'running' "
                "AND owner_generation = $3 RETURNING op_id",
                self.node_id,
                op_id,
                self.ownership.generation,
                reason,
                json.dumps(observed),
            )
        return done is not None

    async def resolve_unknown(self, op_id: str, evidence: dict[str, Any]) -> bool:
        """`outcome_unknown → failed` on ordered reset evidence (design S1, T1).

        Under the dispatch lock, like every other transition that changes
        whether the node is blocked. The evidence is kept in the operation's
        provenance and in the audit trail, which outlives the row.
        """
        async with self._owned(dispatch=True, action="resolution", op_id=op_id) as conn:
            done = await conn.fetchval(
                "UPDATE node_operations SET state = 'failed', reason = 'resolved_by_reset', "
                'terminal = \'{"resolution": "operator_reset"}\'::jsonb, resolved_at = now(), '
                "resolved_by = 'operator', provenance = provenance || $4::jsonb "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'outcome_unknown' "
                "AND owner_generation = $3 RETURNING op_id",
                self.node_id,
                op_id,
                self.ownership.generation,
                json.dumps({"resolution": evidence}),
            )
            if done is not None:
                await conn.execute(
                    "INSERT INTO node_operation_audit (node_id, op_id, event, detail) "
                    "VALUES ($1, $2, 'resolved_by_reset', $3::jsonb)",
                    self.node_id,
                    op_id,
                    json.dumps(evidence),
                )
        return done is not None

    async def checkpoint(self, op_id: str, observed: dict[str, Any]) -> None:
        async with self._owned(dispatch=False, action="checkpoint", op_id=op_id) as conn:
            await conn.execute(
                "UPDATE node_operations SET observed = $4::jsonb "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'running' "
                "AND owner_generation = $3",
                self.node_id,
                op_id,
                self.ownership.generation,
                json.dumps(observed),
            )

    async def finish(
        self,
        op_id: str,
        state: str,
        terminal: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
        replay_unavailable: bool = False,
    ) -> bool:
        """`running → completed | failed`, with the result in the same commit.

        The terminal state and any stored result are committed together before
        the caller acknowledges (design R6). A superseded owner's completion
        fails the ownership proof; it is audited as `stale_completion` and
        clears nothing (design R2).
        """
        if state not in ("completed", "failed"):
            raise ValueError(f"not a terminal state: {state}")
        async with self._owned(dispatch=False, action="completion", op_id=op_id) as conn:
            done = await conn.fetchval(
                "UPDATE node_operations SET state = $4, terminal = $5::jsonb, reason = $6, "
                "replay_unavailable = $7, resolved_at = now(), resolved_by = 'runtime' "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'running' "
                "AND owner_generation = $3 RETURNING op_id",
                self.node_id,
                op_id,
                self.ownership.generation,
                state,
                json.dumps(terminal),
                reason,
                replay_unavailable,
            )
            if done is not None and result is not None:
                await conn.execute(
                    "INSERT INTO attempt_results (node_id, op_id, result) "
                    "VALUES ($1, $2, $3::jsonb)",
                    self.node_id,
                    op_id,
                    json.dumps(result),
                )
        return done is not None

    async def unsent_after_promotion(self, op_id: str, reason: str) -> bool:
        """`running → cancelled_unsent` for a promotion whose task never existed.

        Only for a promotion that raised (a database error, or the caller's
        cancellation) after possibly committing: no task was created, so no
        byte was sent, and only this process can know that. If the process
        dies first, takeover makes the row unknown, which is conservative.
        """
        async with self._owned(dispatch=True, action="unsent", op_id=op_id) as conn:
            done = await conn.fetchval(
                "UPDATE node_operations SET state = 'cancelled_unsent', reason = $4, "
                "resolved_at = now(), resolved_by = 'promotion' "
                "WHERE node_id = $1 AND op_id = $2 AND state = 'running' "
                "AND owner_generation = $3 RETURNING op_id",
                self.node_id,
                op_id,
                self.ownership.generation,
                reason,
            )
        return done is not None

    async def audit(self, event: str, op_id: str | None, detail: dict[str, Any]) -> None:
        """Unfenced: evidence is recorded whoever wrote it."""
        await self._pool.execute(
            "INSERT INTO node_operation_audit (node_id, op_id, event, detail) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            self.node_id,
            op_id,
            event,
            json.dumps(detail),
        )
