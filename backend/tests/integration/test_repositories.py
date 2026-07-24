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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresInvitationRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models import Base
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.entities.user import User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL or "", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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


async def test_node_round_trip(session) -> None:
    repo = PostgresNodeRepository(session)
    await repo.save(_node())
    await session.flush()

    stored = await repo.get("n1")
    assert stored is not None
    # frozenset of enums survives the trip through a JSON array of strings
    assert stored.runtimes == frozenset({RuntimeKind.OLLAMA, RuntimeKind.MLX})
    assert stored.status is NodeStatus.ONLINE
    assert stored.total_memory_gb == 64.0


async def test_model_round_trip_and_alias_lookup(session) -> None:
    await PostgresNodeRepository(session).save(_node())
    repo = PostgresModelRepository(session)
    await repo.save(_model())
    await session.flush()

    stored = await repo.get_by_alias("primary")
    assert stored is not None
    assert stored.capabilities == frozenset({"chat", "code"})
    # resource_profile is flattened into two columns and must reassemble
    assert stored.resource_profile.memory_gb == 18.5
    assert stored.resource_profile.context_length == 32768


async def test_list_loaded_filters_by_state_and_node(session) -> None:
    await PostgresNodeRepository(session).save(_node())
    await PostgresNodeRepository(session).save(_node("n2"))
    repo = PostgresModelRepository(session)

    loaded = _model("loaded-here", "n1")
    elsewhere = _model("loaded-elsewhere", "n2")
    # `replace`, not `__dict__`: the entities are slotted dataclasses.
    idle = replace(_model("idle", "n1"), state=ModelState.DOWNLOADED)

    for entity in (loaded, elsewhere, idle):
        await repo.save(entity)
    await session.flush()

    aliases = {m.alias for m in await repo.list_loaded("n1")}
    assert aliases == {"loaded-here"}


async def test_routing_policy_structured_requirements_round_trip(session) -> None:
    """The requirement document is the part most likely to rot silently.

    It is persisted as JSON and rebuilt field by field, so a mismatch shows up
    as a policy that quietly stops matching rather than as an error.
    """
    repo = PostgresRoutingPolicyRepository(session)
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate(
                model_alias="primary",
                priority=100,
                require=Requirement(
                    node_status=frozenset({NodeStatus.ONLINE}),
                    model_state=frozenset({ModelState.LOADED}),
                    min_free_memory_gb=24.0,
                ),
            ),
            RoutingCandidate(model_alias="fallback", priority=10),
        ),
    )
    await repo.save(policy)
    await session.flush()

    stored = await repo.get("chat")
    assert stored == policy, "requirement document did not survive the round trip"


async def test_api_key_cidrs_round_trip(session) -> None:
    await PostgresUserRepository(session).save(
        User(id="u1", login="a@example.com", display_name="A", role=Role.ADMIN)
    )
    repo = PostgresApiKeyRepository(session)
    expires = datetime.now(UTC) + timedelta(days=90)
    key = ApiKey(
        id=str(uuid.uuid4()),
        key_id="abc123",
        digest="deadbeef",
        name="ci",
        owner_id="u1",
        scopes=frozenset({"chat"}),
        allowed_cidrs=(ip_network("203.0.113.0/24"), ip_network("2001:db8::/32")),
        expires_at=expires,
    )
    await repo.save(key)
    await session.flush()

    stored = await repo.get_by_key_id("abc123")
    assert stored is not None
    # Networks are stored as strings and must come back as network objects,
    # since the CIDR allowlist check compares against them directly.
    assert stored.allowed_cidrs == key.allowed_cidrs
    assert stored.is_active(datetime.now(UTC)) is True

    await repo.revoke("abc123", datetime.now(UTC))
    await session.flush()
    session.expire_all()
    revoked = await repo.get_by_key_id("abc123")
    assert revoked is not None and revoked.is_active(datetime.now(UTC)) is False


async def test_user_count_backs_the_bootstrap_guard(session) -> None:
    repo = PostgresUserRepository(session)
    assert await repo.count() == 0, "a fresh deployment must look empty"

    await repo.save(User(id="u1", login="a@example.com", display_name="A", role=Role.ADMIN))
    await session.flush()
    assert await repo.count() == 1, "bootstrap must become inert once anyone exists"


async def test_issuing_a_new_link_invalidates_the_previous_one(session) -> None:
    """Otherwise an intercepted reset link stays usable after the real user
    asks for another."""
    await PostgresUserRepository(session).save(
        User(id="u1", login="a@example.com", display_name="A", role=Role.USER)
    )
    repo = PostgresInvitationRepository(session)
    expires = datetime.now(UTC) + timedelta(hours=72)

    first = Invitation(
        id=str(uuid.uuid4()),
        user_id="u1",
        token_hash="hash-one",  # noqa: S106  (a stand-in digest, not a credential)
        purpose=InvitationPurpose.PASSWORD_RESET,
        expires_at=expires,
    )
    await repo.save(first)
    await session.flush()

    await repo.invalidate_outstanding("u1", InvitationPurpose.PASSWORD_RESET)
    await session.flush()

    assert await repo.get_by_token_hash("hash-one") is None


async def test_usage_totals_only_count_the_named_key(session) -> None:
    repo = PostgresUsageRepository(session)
    now = datetime.now(UTC)
    for key_id, tokens in (("k1", 100), ("k1", 50), ("k2", 999)):
        await repo.record(
            UsageRecord(
                id=str(uuid.uuid4()),
                actor_id="u1",
                api_key_id=key_id,
                capability="chat",
                model_alias="primary",
                tokens=tokens,
                latency_ms=10,
                completed=True,
                at=now,
            )
        )
    await session.flush()

    assert await repo.tokens_used_today("k1") == 150
