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
from sqlalchemy.exc import IntegrityError
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
    await session.flush()
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
    await session.flush()
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


async def test_an_intent_write_clears_the_observation_beside_it(session) -> None:
    """The pairing `set_state` promises, against the real UPDATE.

    Every reader ranks the observation over the intent, so an observation taken
    before a transition would outrank the transition itself: a model loaded a
    moment ago would keep routing as `downloaded` until the next sweep, and a
    `model_state: [loaded]` policy with one candidate would answer 503 for
    resident weights. This is pinned here rather than in the unit suite because
    the use cases reach `set_state` only after a state committer has already
    written — so a unit test of `load` passes whether or not this clause exists.
    """
    await PostgresNodeRepository(session).save(_node())
    await session.flush()
    repo = PostgresModelRepository(session)
    model = replace(_model(), state=ModelState.DOWNLOADED)
    await repo.save(model)
    await session.flush()

    await repo.set_observed(model.id, ModelState.DOWNLOADED, None)
    await session.flush()
    observed = await repo.get(model.id)
    assert observed is not None and observed.observed_at is not None

    await repo.set_state(model.id, ModelState.LOADED)
    await session.flush()

    stored = await repo.get(model.id)
    assert stored is not None
    assert stored.state is ModelState.LOADED
    assert stored.observed_state is None, "an observation predating the write must not survive it"
    assert stored.observed_memory_gb is None
    assert stored.observed_at is None, "the timestamp goes with the observation it dated"


async def test_an_unobservable_runtime_clears_rather_than_asserting_absence(session) -> None:
    """`set_observed(None, None)` is the heartbeat saying "could not ask", which
    must not read as "nothing is resident": the timestamp is cleared with it, so
    no reader can mistake a stale observation for a fresh one."""
    await PostgresNodeRepository(session).save(_node())
    await session.flush()
    repo = PostgresModelRepository(session)
    model = _model()
    await repo.save(model)
    await session.flush()

    await repo.set_observed(model.id, ModelState.LOADED, 5.7)
    await session.flush()
    seen = await repo.get(model.id)
    assert seen is not None and seen.observed_memory_gb == 5.7

    await repo.set_observed(model.id, None, None)
    await session.flush()

    cleared = await repo.get(model.id)
    assert cleared is not None
    assert cleared.observed_state is None
    assert cleared.observed_at is None
    assert cleared.state is ModelState.LOADED, "intent is untouched by an observation write"


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
    await PostgresUserRepository.unscoped(session).save(
        User(id="u1", login="a@example.com", display_name="A", role=Role.ADMIN)
    )
    await session.flush()  # parent first; autoflush is off, as in production
    repo = PostgresApiKeyRepository.unscoped(session)
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
    repo = PostgresUserRepository.unscoped(session)
    assert await repo.count() == 0, "a fresh deployment must look empty"

    await repo.save(User(id="u1", login="a@example.com", display_name="A", role=Role.ADMIN))
    await session.flush()
    assert await repo.count() == 1, "bootstrap must become inert once anyone exists"


async def test_issuing_a_new_link_invalidates_the_previous_one(session) -> None:
    """Otherwise an intercepted reset link stays usable after the real user
    asks for another."""
    await PostgresUserRepository.unscoped(session).save(
        User(id="u1", login="a@example.com", display_name="A", role=Role.USER)
    )
    await session.flush()
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


async def test_consuming_a_link_twice_reports_the_second_as_a_loss(session) -> None:
    """The atomic claim is meaningless unless its result is checked.

    Two requests reaching the same link both find `consumed_at IS NULL` and
    both call consume; only one updates a row. Discarding the rowcount left
    both believing they had claimed it, which is exactly the interception case
    the single-use rule exists for.
    """
    await PostgresUserRepository.unscoped(session).save(
        User(id="u1", login="a@example.com", display_name="A", role=Role.USER)
    )
    await session.flush()
    repo = PostgresInvitationRepository(session)
    invitation = Invitation(
        id=str(uuid.uuid4()),
        user_id="u1",
        token_hash="hash-race",  # noqa: S106  (a stand-in digest)
        purpose=InvitationPurpose.ONBOARD,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await repo.save(invitation)
    await session.flush()

    assert await repo.consume(invitation.id, datetime.now(UTC)) is True
    assert await repo.consume(invitation.id, datetime.now(UTC)) is False


async def test_a_totp_counter_cannot_be_replayed(session) -> None:
    """Replay prevention has to happen in the UPDATE.

    Comparing against a counter read earlier and writing it back lets two
    requests carrying the same code both pass, which is how a code observed in
    a phishing proxy stays usable inside its window.
    """
    repo = PostgresUserRepository.unscoped(session)
    await repo.save(
        User(
            id="u1",
            login="a@example.com",
            display_name="A",
            role=Role.USER,
            password_hash="argon2-hash",  # noqa: S106
            totp_secret="secret",  # noqa: S106
        )
    )
    await session.flush()

    assert await repo.advance_totp_counter("u1", 100) is True
    assert await repo.advance_totp_counter("u1", 100) is False, "same counter replayed"
    assert await repo.advance_totp_counter("u1", 99) is False, "older counter accepted"
    assert await repo.advance_totp_counter("u1", 101) is True


async def test_the_schema_refuses_a_password_without_a_second_factor(session) -> None:
    """ "An account never exists in a password-only state" was a Python
    property, so a direct write could produce the state the design calls
    impossible. It is a check constraint now.

    The violation surfaces from `save` rather than from a later flush, because
    `save` now flushes: `users` is a foreign key target and these models carry
    no `relationship()`, so without that flush the unit of work has nothing to
    order dependent inserts by.
    """
    repo = PostgresUserRepository.unscoped(session)
    with pytest.raises(IntegrityError):
        await repo.save(
            User(
                id="u1",
                login="a@example.com",
                display_name="A",
                role=Role.USER,
                password_hash="argon2-hash",  # noqa: S106
                totp_secret=None,
            )
        )


async def test_usage_totals_only_count_the_named_key(session) -> None:
    repo = PostgresUsageRepository.unscoped(session)
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


async def test_a_spent_quota_recovers_one_past_request_at_a_time(session) -> None:
    """The window trails 24 hours rather than resetting at midnight, so the
    wait after exhausting a quota is set by when the *oldest* spend ages out —
    and only by as much of it as has to go. Three requests of 100 against a
    quota of 250 sit 50 over; releasing the first 100 is enough, so the wait
    runs from that one, not from the newest and not from all three.

    Getting this wrong is invisible in the response: it is still a 429, just
    with a `Retry-After` that sends the caller back too early or too late.
    """
    repo = PostgresUsageRepository.unscoped(session)
    now = datetime.now(UTC)
    ages = (timedelta(hours=20), timedelta(hours=10), timedelta(minutes=5))
    for age in ages:
        await repo.record(
            UsageRecord(
                id=str(uuid.uuid4()),
                actor_id="u1",
                api_key_id="k3",
                capability="chat",
                model_alias="primary",
                tokens=60,
                prompt_tokens=40,
                latency_ms=10,
                completed=True,
                at=now - age,
            )
        )
    await session.flush()

    assert await repo.tokens_used_today("k3") == 300

    # 300 used against a quota of 250: release 51 to be admitted again.
    recovers_at = await repo.quota_recovers_at("k3", tokens_to_release=300 - 250 + 1)
    assert recovers_at is not None
    expected = now - timedelta(hours=20) + timedelta(days=1)
    assert abs((recovers_at - expected).total_seconds()) < 1

    # Needing more than the window holds cannot be answered from it.
    assert await repo.quota_recovers_at("k3", tokens_to_release=301) is None
