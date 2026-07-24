"""Test doubles for the authentication use cases.

These implement the repository and security ports directly rather than
wrapping a mock, because the behaviour under test is mostly about *which*
method is called and in what order: that a dummy hash runs before an unknown
login is refused, that a counter is claimed with a conditional write rather
than a comparison. A mock that answers anything would pass those tests while
the production wiring did nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from app.domain.entities.actor import Actor
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.user import User


class FakeUsers:
    def __init__(self, users: Sequence[User] = ()) -> None:
        self.rows: dict[str, User] = {u.id: u for u in users}
        self.counter_claims: list[tuple[str, int]] = []

    async def get(self, user_id: str) -> User | None:
        return self.rows.get(user_id)

    async def get_by_login(self, login: str) -> User | None:
        return next((u for u in self.rows.values() if u.login == login), None)

    async def get_by_tailscale_login(self, login: str) -> User | None:
        return next((u for u in self.rows.values() if u.tailscale_login == login), None)

    async def list_all(self) -> list[User]:
        return list(self.rows.values())

    async def count(self) -> int:
        return len(self.rows)

    async def save(self, user: User) -> None:
        self.rows[user.id] = user

    async def insert_if_absent(self, user: User) -> User:
        existing = await self.get_by_login(user.login)
        if existing is not None:
            return existing
        self.rows[user.id] = user
        return user

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        """Models the conditional UPDATE, including that it refuses to move
        backwards. A version that always returned True would let every replay
        test pass against a broken implementation."""
        self.counter_claims.append((user_id, counter))
        user = self.rows[user_id]
        if user.totp_last_counter is not None and counter <= user.totp_last_counter:
            return False
        self.rows[user_id] = replace(user, totp_last_counter=counter)
        return True

    async def set_disabled(self, user_id: str, at: datetime | None) -> None:
        self.rows[user_id] = replace(self.rows[user_id], disabled_at=at)


class FakeInvitations:
    def __init__(self) -> None:
        self.rows: dict[str, Invitation] = {}
        self.codes: dict[str, RecoveryCode] = {}

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        return next((i for i in self.rows.values() if i.token_hash == token_hash), None)

    async def save(self, invitation: Invitation) -> None:
        self.rows[invitation.id] = invitation

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        invitation = self.rows.get(invitation_id)
        if invitation is None or invitation.consumed_at is not None:
            return False
        self.rows[invitation_id] = replace(invitation, consumed_at=at)
        return True

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None:
        self.rows = {
            k: v
            for k, v in self.rows.items()
            if not (v.user_id == user_id and v.purpose == purpose and v.consumed_at is None)
        }

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None:
        for code in codes:
            self.codes[code.id] = code

    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]:
        return [c for c in self.codes.values() if c.user_id == user_id]

    async def delete_recovery_codes(self, user_id: str) -> None:
        self.codes = {k: v for k, v in self.codes.items() if v.user_id != user_id}

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool:
        code = self.codes.get(code_id)
        if code is None or code.used_at is not None:
            return False
        self.codes[code_id] = replace(code, used_at=at)
        return True


class FakeHasher:
    """Reversible on purpose: the tests are about control flow, not argon2.

    `dummy_calls` is what the enumeration tests assert on, since the defence
    is "comparable work happened", not "a particular value was returned".
    """

    def __init__(self) -> None:
        self.dummy_calls = 0

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{password}"

    async def dummy_verify(self) -> None:
        self.dummy_calls += 1


class FakeSecretBox:
    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str | None, str]] = []

    async def record(
        self,
        actor: Actor,
        action: str,
        *,
        target: str | None = None,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None:
        self.entries.append((action, target, outcome))

    def actions(self) -> list[str]:
        return [action for action, _, _ in self.entries]


class FakeSessions:
    def __init__(self) -> None:
        self.invalidated_all: list[str] = []
        self.invalidated_others: list[tuple[str, str]] = []

    async def invalidate_all(self, user_id: str, now: datetime) -> None:
        self.invalidated_all.append(user_id)

    async def invalidate_others(self, user_id: str, keep_session_id: str, now: datetime) -> None:
        self.invalidated_others.append((user_id, keep_session_id))


class AcceptingPolicy:
    def assert_acceptable(self, password: str, *, user_inputs: Sequence[str] = ()) -> None:
        return None
