from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import pytest
from sqlalchemy.exc import IntegrityError

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresInvitationRepository,
    PostgresUserRepository,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose
from app.domain.entities.user import User
from tests.integration.repository_fixtures import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.repository_fixtures",)


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
