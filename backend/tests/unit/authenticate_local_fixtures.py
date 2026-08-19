"""Login rules from docs/architecture/security.md section 5.3.

Each of these is a control that fails silently if it regresses: enumeration
resistance produces no error, a replayed TOTP code produces a successful
login, and a throttle that runs after the hash still returns 429 while having
already done the work it was meant to prevent.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.domain.entities.actor import Role
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
)
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.token_service import TokenService
from app.shared.clock import FixedClock
from tests.unit.fakes import FakeAudit, FakeHasher, FakeInvitations, FakeSecretBox, FakeUsers

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)

IP = "203.0.113.7"

SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105  (a test fixture)


def make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": "u1",
        "login": "someone@example.org",
        "display_name": "Someone",
        "role": Role.USER,
        "password_hash": "hashed:correct horse battery staple",
        "totp_secret": f"enc:{SECRET}",
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def build(users: FakeUsers, invitations: FakeInvitations | None = None):
    hasher = FakeHasher()
    audit = FakeAudit()
    use_case = AuthenticateLocal(
        users=users,
        hasher=hasher,
        totp=PyotpTotp(),
        invitations=invitations or FakeInvitations(),
        tokens=TokenService(),
        throttle=LoginThrottle(InMemoryCache()),
        secret_box=FakeSecretBox(),
        audit=audit,
        clock=FixedClock(NOW),
    )
    return use_case, hasher, audit


class RacingUsers(FakeUsers):
    """Advances the stored counter between the caller's read and its write.

    This is the only way to reach the conditional UPDATE's refusal, and writing
    it out is the point: a *sequential* replay never gets that far, because
    `TotpPort.verify` already rejects a counter at or below the stored one. The
    UPDATE exists for two requests carrying the same code at the same moment,
    where both read the old counter and both pass that check.
    """

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        self.rows[user_id] = replace(self.rows[user_id], totp_last_counter=counter)
        return await super().advance_totp_counter(user_id, counter)


async def _exhaust_the_limiter(use_case) -> None:
    for _ in range(6):
        with pytest.raises(InvalidCredentialsError):
            await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)
