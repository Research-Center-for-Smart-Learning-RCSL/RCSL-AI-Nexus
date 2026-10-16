"""Attempt-local snapshots and racing unsent retries on real PostgreSQL (#32)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.adapters.persistence.repositories import PostgresRequestBindings
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from tests.integration.conftest import _alembic_config


async def test_racing_rebinds_keep_only_the_winners_snapshot(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    bindings = PostgresRequestBindings(sessions)
    original = {"model_alias": "original", "started_at": "2026-10-08T00:00:00+00:00"}
    try:
        first = await bindings.create(
            tenant_id=DEFAULT_TENANT_ID,
            request_id="k:race-billing",
            payload_hash="v1:hash",
            hash_version="v1",
            key_supplied=True,
            billing=original,
            node_id="original-node",
            op_id=str(uuid.uuid4()),
        )
        contenders = {
            str(uuid.uuid4()): {"model_alias": f"model-{i}", "node_id": f"node-{i}"}
            for i in range(3)
        }
        results = await asyncio.gather(
            *(
                bindings.rebind(first, node_id=billing["node_id"], op_id=op_id, billing=billing)
                for op_id, billing in contenders.items()
            )
        )
        winner = results[0]
        assert all(result == winner for result in results)
        assert winner.seq == 2 and winner.version == 1
        assert winner.billing == contenders[winner.op_id]
        assert winner.node_id == winner.billing["node_id"]
        assert (winner.payload_hash, winner.hash_version) == (
            first.payload_hash,
            first.hash_version,
        )

        async with sessions() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT op_id, billing, retry_of_seq FROM request_attempts ORDER BY seq"
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        assert rows[0]["billing"] == original and rows[0]["retry_of_seq"] is None
        assert rows[1]["billing"] == winner.billing and rows[1]["retry_of_seq"] == 1
    finally:
        await engine.dispose()


async def test_snapshot_insert_failure_rolls_back_the_rebind(database_url: str) -> None:
    engine = create_async_engine(database_url)
    bindings = PostgresRequestBindings(async_sessionmaker(engine, expire_on_commit=False))
    try:
        first = await bindings.create(
            tenant_id=DEFAULT_TENANT_ID,
            request_id="k:rollback-billing",
            payload_hash="v1:hash",
            hash_version="v1",
            key_supplied=True,
            billing={"model_alias": "original"},
            node_id="original-node",
            op_id=str(uuid.uuid4()),
        )
        invalid: dict[str, Any] = {"not_json": object()}
        with pytest.raises(TypeError, match="not JSON serializable"):
            await bindings.rebind(first, node_id="retry", op_id=str(uuid.uuid4()), billing=invalid)
        assert await bindings.lookup(first.tenant_id, first.request_id) == first
    finally:
        await engine.dispose()


async def test_schema_upgrade_preserves_old_gateway_attempts(database_url: str) -> None:
    """Old INSERTs work after migration, and legacy data survives down/up."""
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    original = {"model_ref": "old:latest", "actor_id": "original"}
    op_id = str(uuid.uuid4())
    try:
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO request_bindings (tenant_id, request_id, current_seq, "
                    "payload_hash, hash_version, key_supplied, billing) "
                    "VALUES (:tenant, 'k:legacy', 1, 'v1:hash', 'v1', true, "
                    "CAST(:billing AS jsonb))"
                ),
                {"tenant": DEFAULT_TENANT_ID, "billing": json.dumps(original)},
            )
            await session.execute(
                text(
                    "INSERT INTO request_attempts (tenant_id, request_id, seq, node_id, op_id) "
                    "VALUES (:tenant, 'k:legacy', 1, 'legacy-node', :op_id)"
                ),
                {"tenant": DEFAULT_TENANT_ID, "op_id": op_id},
            )
        config = _alembic_config(database_url)
        await asyncio.to_thread(command.downgrade, config, "a8d3f61c2e47")
        await asyncio.to_thread(command.upgrade, config, "head")
        bound = await PostgresRequestBindings(sessions).lookup(DEFAULT_TENANT_ID, "k:legacy")
        assert bound is not None and bound.op_id == op_id and bound.billing == original
    finally:
        await engine.dispose()
