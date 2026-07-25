"""The tenant boundary, against a real Postgres.

This is the security property of section 7.3: a repository scoped to one tenant
can neither read nor write another's rows, and the filter lives in the adapter so
a use case cannot forget it. The unit tests cannot prove this, because the fakes
have no notion of the filter; only the real WHERE clause does.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresTenantRepository,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import UsageRecord
from app.domain.entities.user import User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

NOW = datetime(2026, 7, 25, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def _tenant(session, name: str) -> str:
    tid = str(uuid.uuid4())
    await PostgresTenantRepository(session).save(Tenant(id=tid, name=name))
    return tid


def _user(tenant_id: str, login: str) -> User:
    return User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        login=login,
        display_name=login,
        role=Role.ADMIN,
    )


def _key(tenant_id: str, key_id: str, owner_id: str) -> ApiKey:
    return ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        key_id=key_id,
        digest="digest",
        name=key_id,
        owner_id=owner_id,
        expires_at=FUTURE,
    )


async def test_scoped_user_repo_sees_only_its_tenant(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    await PostgresUserRepository(session, a).save(_user(a, "a@example.org"))
    await PostgresUserRepository(session, b).save(_user(b, "b@example.org"))

    assert [u.login for u in await PostgresUserRepository(session, a).list_all()] == [
        "a@example.org"
    ]
    assert [u.login for u in await PostgresUserRepository(session, b).list_all()] == [
        "b@example.org"
    ]
    # The unscoped repository (identity/bootstrap path) sees across tenants.
    assert len(await PostgresUserRepository.unscoped(session).list_all()) >= 2


async def test_scoped_user_repo_cannot_fetch_another_tenants_user_by_id(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    await PostgresUserRepository(session, a).save(_user(a, "a@example.org"))
    b_user = _user(b, "b@example.org")
    await PostgresUserRepository(session, b).save(b_user)

    # Even knowing the id, tenant A's repository does not return B's row.
    assert await PostgresUserRepository(session, a).get(b_user.id) is None
    assert await PostgresUserRepository(session, b).get(b_user.id) is not None


async def test_a_scoped_save_stamps_the_repos_tenant(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    # The entity claims tenant B, but it is saved through tenant A's repository.
    await PostgresUserRepository(session, a).save(_user(b, "c@example.org"))

    stored = await PostgresUserRepository.unscoped(session).get_by_login("c@example.org")
    assert stored is not None
    assert stored.tenant_id == a, "the scoped repository stamps its own tenant, not the entity's"


async def test_scoped_key_repo_cannot_reach_another_tenants_key(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    a_owner = _user(a, "a@example.org")
    b_owner = _user(b, "b@example.org")
    await PostgresUserRepository(session, a).save(a_owner)
    await PostgresUserRepository(session, b).save(b_owner)
    await PostgresApiKeyRepository(session, a).save(_key(a, "ka", a_owner.id))
    await PostgresApiKeyRepository(session, b).save(_key(b, "kb", b_owner.id))

    # Listing and by-handle lookup are both filtered.
    assert [k.key_id for k in await PostgresApiKeyRepository(session, a).list_all()] == ["ka"]
    assert await PostgresApiKeyRepository(session, a).get_by_key_id("kb") is None

    # A scoped revoke of another tenant's key touches nothing.
    await PostgresApiKeyRepository(session, a).revoke("kb", NOW)
    survivor = await PostgresApiKeyRepository.unscoped(session).get_by_key_id("kb")
    assert survivor is not None and survivor.revoked_at is None


async def test_usage_totals_are_scoped_to_the_tenant(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    await PostgresUsageRepository(session, a).record(
        UsageRecord(
            id=str(uuid.uuid4()),
            actor_id="x",
            api_key_id="ka",
            capability="chat",
            model_alias="m",
            tokens=10,
            latency_ms=1,
            completed=True,
            at=NOW,
            tenant_id=a,
        )
    )
    await PostgresUsageRepository(session, b).record(
        UsageRecord(
            id=str(uuid.uuid4()),
            actor_id="y",
            api_key_id="kb",
            capability="chat",
            model_alias="m",
            tokens=99,
            latency_ms=1,
            completed=True,
            at=NOW,
            tenant_id=b,
        )
    )
    await session.flush()

    since = NOW - timedelta(hours=1)
    requests_a, tokens_a = await PostgresUsageRepository(session, a).totals_since(since)
    assert (requests_a, tokens_a) == (1, 10), "tenant A sees only its own usage"
