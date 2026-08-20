"""Repository round-trips against a real Postgres.

Skipped unless TEST_DATABASE_URL is set, deliberately a different variable
from DATABASE_URL so that running the unit suite can never reach a database,
let alone a real one.

What is worth testing here is the mapping layer, not SQLAlchemy. Domain
entities use frozensets, enums, and ip_network objects; rows use JSON arrays
and strings. Every one of those conversions is a place where a value can come
back subtly different from how it went in, and none of it is exercised by the
unit tests.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def session(database_url):
    """Schema built by Alembic (see conftest), and session parameters matching
    production, so what passes here reflects what will happen there."""
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _node(node_id: str = "n1") -> Node:
    return Node(
        id=node_id,
        name=f"name-{node_id}",
        address="100.64.0.1",
        status=NodeStatus.ONLINE,
        total_memory_gb=64.0,
        runtimes=frozenset({RuntimeKind.OLLAMA, RuntimeKind.MLX}),
    )


def _model(alias: str = "primary", node_id: str = "n1") -> Model:
    return Model(
        id=str(uuid.uuid4()),
        alias=alias,
        ref=f"{alias}:32b",
        runtime=RuntimeKind.OLLAMA,
        node_id=node_id,
        state=ModelState.LOADED,
        capabilities=frozenset({"chat", "code"}),
        resource_profile=ResourceProfile(memory_gb=18.5, context_length=32768),
    )
