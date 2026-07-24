"""Persistence behaviour the authentication flows depend on.

Every case here is one where an in-memory double agrees with a broken
implementation. The atomic claims either hold in Postgres or they do not, and
the check constraint on `users` either rejects a half-written account or it
does not; neither can be established anywhere but against a real database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.adapters.persistence.repositories import (
    PostgresInvitationRepository,
    PostgresUserRepository,
)
from app.domain.entities.actor import Role
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.user import User
from tests.integration.conftest import make_session_factory

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


async def persist(sessions, user: User) -> User:
    """Commit the user before anything that references it.

    The ORM models declare foreign key *columns* but no `relationship()`, so
    SQLAlchemy's unit of work has no dependency graph to order a flush by. With
    `autoflush=False` — which production uses, and which the test sessions
    mirror deliberately — a user and its recovery codes added to one session
    can be inserted in either order. Production never has this problem because
    the two happen in different requests, and the tests say so explicitly
    rather than relying on an implicit flush.
    """
    async with sessions() as session:
        await PostgresUserRepository(session).save(user)
        await session.commit()
    return user


def make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "login": f"user-{uuid.uuid4().hex[:8]}@example.org",
        "display_name": "Test User",
        "role": Role.USER,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


async def test_created_at_is_assigned_by_the_database(database_url: str) -> None:
    """The column has a server default, so the application never has to decide
    what "created" means and a client clock cannot set it."""
    sessions = make_session_factory(database_url)
    user = make_user()

    async with sessions() as session:
        await PostgresUserRepository(session).save(user)
        await session.commit()

    async with sessions() as session:
        stored = await PostgresUserRepository(session).get(user.id)

    assert stored is not None
    assert stored.created_at is not None


async def test_insert_if_absent_returns_the_existing_row(database_url: str) -> None:
    """The bootstrap guard. Two requests from one page load both see an empty
    table and both try to create the same login; the loser must receive the
    winner's row rather than a constraint violation.
    """
    sessions = make_session_factory(database_url)
    login = "founder@example.org"

    async with sessions() as session:
        first = await PostgresUserRepository(session).insert_if_absent(
            make_user(login=login, role=Role.ADMIN)
        )
        await session.commit()

    async with sessions() as session:
        second = await PostgresUserRepository(session).insert_if_absent(
            make_user(login=login, role=Role.ADMIN)
        )
        await session.commit()

    assert first.id == second.id


async def test_an_account_cannot_be_left_with_a_password_and_no_second_factor(
    database_url: str,
) -> None:
    """Enforced by the database, not by a Python property, because the property
    cannot stop a second writer or a half-finished invitation."""
    sessions = make_session_factory(database_url)

    with pytest.raises(IntegrityError):
        async with sessions() as session:
            await PostgresUserRepository(session).save(
                make_user(password_hash="argon2-ish", totp_secret=None)  # noqa: S106
            )
            await session.commit()


async def test_a_recovery_code_can_only_be_claimed_once(database_url: str) -> None:
    """A recovery code bypasses the second factor outright, so one that can be
    redeemed twice is worse than an invitation that can."""
    sessions = make_session_factory(database_url)
    user = await persist(sessions, make_user())
    code_id = str(uuid.uuid4())

    async with sessions() as session:
        await PostgresInvitationRepository(session).save_recovery_codes(
            [RecoveryCode(id=code_id, user_id=user.id, code_hash="deadbeef")]
        )
        await session.commit()

    async with sessions() as session:
        repo = PostgresInvitationRepository(session)
        assert await repo.consume_recovery_code(code_id, NOW) is True
        assert await repo.consume_recovery_code(code_id, NOW) is False
        await session.commit()


async def test_reissuing_recovery_codes_removes_the_previous_set(database_url: str) -> None:
    """Codes printed against a secret the user no longer holds must not stay
    redeemable, or re-enrolment leaves a standing bypass behind it."""
    sessions = make_session_factory(database_url)
    user = await persist(sessions, make_user())

    async with sessions() as session:
        await PostgresInvitationRepository(session).save_recovery_codes(
            [
                RecoveryCode(id=str(uuid.uuid4()), user_id=user.id, code_hash=f"old-{i}")
                for i in range(3)
            ]
        )
        await session.commit()

    async with sessions() as session:
        repo = PostgresInvitationRepository(session)
        await repo.delete_recovery_codes(user.id)
        await repo.save_recovery_codes(
            [RecoveryCode(id=str(uuid.uuid4()), user_id=user.id, code_hash="new-0")]
        )
        await session.commit()

    async with sessions() as session:
        remaining = await PostgresInvitationRepository(session).list_recovery_codes(user.id)

    assert [c.code_hash for c in remaining] == ["new-0"]


async def test_issuing_a_link_invalidates_the_outstanding_one_of_that_purpose(
    database_url: str,
) -> None:
    """Scoped to the purpose: issuing a reset must not silently cancel an
    onboarding link that has not been used yet."""
    sessions = make_session_factory(database_url)
    user = await persist(sessions, make_user())

    async with sessions() as session:
        repo = PostgresInvitationRepository(session)
        for purpose, token in (
            (InvitationPurpose.ONBOARD, "hash-onboard"),
            (InvitationPurpose.PASSWORD_RESET, "hash-reset"),
        ):
            await repo.save(
                Invitation(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    token_hash=token,
                    purpose=purpose,
                    expires_at=NOW + timedelta(hours=72),
                )
            )
        await session.commit()

    async with sessions() as session:
        repo = PostgresInvitationRepository(session)
        await repo.invalidate_outstanding(user.id, InvitationPurpose.PASSWORD_RESET)
        await session.commit()

    async with sessions() as session:
        repo = PostgresInvitationRepository(session)
        assert await repo.get_by_token_hash("hash-onboard") is not None
        assert await repo.get_by_token_hash("hash-reset") is None


async def test_a_totp_counter_cannot_move_backwards(database_url: str) -> None:
    """The replay check is this UPDATE. A Python comparison against a value
    read earlier admits both of two concurrent requests carrying one code."""
    sessions = make_session_factory(database_url)
    user = await persist(
        sessions,
        make_user(password_hash="argon2-ish", totp_secret="enc:secret"),  # noqa: S106
    )

    async with sessions() as session:
        repo = PostgresUserRepository(session)
        assert await repo.advance_totp_counter(user.id, 100) is True
        assert await repo.advance_totp_counter(user.id, 100) is False
        assert await repo.advance_totp_counter(user.id, 99) is False
        assert await repo.advance_totp_counter(user.id, 101) is True
        await session.commit()
