"""`request_bindings` and `request_attempts` (design R6/S6 on #24).

Its own transactions, never the request's session: a binding must be visible
to a concurrent copy of the same keyed request **before** anything is
forwarded, and the request's session commits only when the request ends.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.attempt import Binding

_LOOKUP = text(
    "SELECT b.tenant_id, b.request_id, b.payload_hash, b.hash_version, b.key_supplied, "
    "b.version, b.current_seq, b.billing, a.node_id, a.op_id "
    "FROM request_bindings b JOIN request_attempts a "
    "ON a.tenant_id = b.tenant_id AND a.request_id = b.request_id AND a.seq = b.current_seq "
    "WHERE b.tenant_id = :tenant_id AND b.request_id = :request_id"
)


class PostgresRequestBindings:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def lookup(self, tenant_id: str, request_id: str) -> Binding | None:
        async with self._sessions() as session:
            row = (
                (await session.execute(_LOOKUP, {"tenant_id": tenant_id, "request_id": request_id}))
                .mappings()
                .first()
            )
        return _binding(row) if row else None

    async def create(
        self,
        *,
        tenant_id: str,
        request_id: str,
        payload_hash: str,
        hash_version: str,
        key_supplied: bool,
        billing: dict[str, Any],
        node_id: str,
        op_id: str,
    ) -> Binding:
        # The binding and its first attempt in one transaction. A concurrent
        # insert of the same key waits on the primary key until the winner
        # commits, so the loser always reads a binding with its attempt.
        async with self._sessions() as session, session.begin():
            won = (
                await session.execute(
                    text(
                        "INSERT INTO request_bindings (tenant_id, request_id, current_seq, "
                        "payload_hash, hash_version, key_supplied, billing) "
                        "VALUES (:tenant_id, :request_id, 1, :payload_hash, :hash_version, "
                        ":key_supplied, CAST(:billing AS jsonb)) "
                        "ON CONFLICT (tenant_id, request_id) DO NOTHING RETURNING request_id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "request_id": request_id,
                        "payload_hash": payload_hash,
                        "hash_version": hash_version,
                        "key_supplied": key_supplied,
                        "billing": json.dumps(billing),
                    },
                )
            ).first()
            if won is not None:
                await session.execute(
                    text(
                        "INSERT INTO request_attempts (tenant_id, request_id, seq, node_id, op_id) "
                        "VALUES (:tenant_id, :request_id, 1, :node_id, :op_id)"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "request_id": request_id,
                        "node_id": node_id,
                        "op_id": op_id,
                    },
                )
        found = await self.lookup(tenant_id, request_id)
        if found is None:  # pragma: no cover - bindings are never deleted
            raise RuntimeError(f"binding {request_id} vanished after it was written")
        return found

    async def rebind(self, binding: Binding, *, node_id: str, op_id: str) -> Binding:
        # Conditional on the version this caller saw: of two rebinds, one wins
        # and the other re-reads and converges on it (design S6).
        async with self._sessions() as session, session.begin():
            moved = (
                await session.execute(
                    text(
                        "UPDATE request_bindings SET current_seq = current_seq + 1, "
                        "version = version + 1 "
                        "WHERE tenant_id = :tenant_id AND request_id = :request_id "
                        "AND version = :version RETURNING current_seq"
                    ),
                    {
                        "tenant_id": binding.tenant_id,
                        "request_id": binding.request_id,
                        "version": binding.version,
                    },
                )
            ).first()
            if moved is not None:
                await session.execute(
                    text(
                        "INSERT INTO request_attempts (tenant_id, request_id, seq, node_id, "
                        "op_id, retry_of_seq) "
                        "VALUES (:tenant_id, :request_id, :seq, :node_id, :op_id, :retry_of)"
                    ),
                    {
                        "tenant_id": binding.tenant_id,
                        "request_id": binding.request_id,
                        "seq": moved[0],
                        "node_id": node_id,
                        "op_id": op_id,
                        "retry_of": binding.seq,
                    },
                )
        found = await self.lookup(binding.tenant_id, binding.request_id)
        if found is None:  # pragma: no cover - bindings are never deleted
            raise RuntimeError(f"binding {binding.request_id} vanished after it was written")
        return found


def _binding(row: Any) -> Binding:
    billing = row["billing"]
    return Binding(
        tenant_id=row["tenant_id"],
        request_id=row["request_id"],
        payload_hash=row["payload_hash"],
        hash_version=row["hash_version"],
        key_supplied=row["key_supplied"],
        version=row["version"],
        seq=row["current_seq"],
        node_id=row["node_id"],
        op_id=row["op_id"],
        billing=billing if isinstance(billing, dict) else json.loads(billing),
    )
