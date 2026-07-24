"""Password then TOTP authentication for the public entrance.

This is a use case rather than middleware logic because it carries real
rules that deserve unit tests: enumeration resistance, TOTP replay
rejection, and the refusal to authenticate an account whose second factor
was never enrolled. See docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTotpError,
    TotpRequiredError,
)
from app.domain.ports.repositories import UserRepositoryPort
from app.domain.ports.security_ports import PasswordHasherPort, TotpPort


@dataclass(frozen=True, slots=True)
class PasswordResult:
    user_id: str
    """Held by the caller between the two login steps. Carries no privilege
    on its own: a session is only issued after the TOTP step succeeds."""


class AuthenticateLocal:
    def __init__(
        self,
        users: UserRepositoryPort,
        hasher: PasswordHasherPort,
        totp: TotpPort,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._totp = totp

    async def verify_password(self, login: str, password: str) -> PasswordResult:
        user = await self._users.get_by_login(login)

        if user is None:
            # Burn comparable time before failing, so response latency does
            # not distinguish an unknown login from a wrong password. Without
            # this, timing enumerates valid accounts.
            self._hasher.dummy_verify()
            raise InvalidCredentialsError(detail=f"unknown login={login}")

        if user.disabled_at is not None:
            self._hasher.dummy_verify()
            raise InvalidCredentialsError(detail=f"disabled user={user.id}")

        if not user.can_use_public_entrance:
            # Tailnet-only account, or an invitation that was never completed.
            # Same error as above: whether an account has local credentials is
            # not something an unauthenticated caller should be able to probe.
            self._hasher.dummy_verify()
            raise InvalidCredentialsError(detail=f"no local credentials user={user.id}")

        # Implied by can_use_public_entrance above, but bound to a local so the
        # narrowing survives without an `assert`, which python -O would strip.
        password_hash = user.password_hash
        if password_hash is None or not self._hasher.verify(password, password_hash):
            raise InvalidCredentialsError(detail=f"bad password user={user.id}")

        return PasswordResult(user_id=user.id)

    async def verify_totp(self, user_id: str, code: str) -> User:
        user = await self._users.get(user_id)
        if user is None or user.totp_secret is None:
            raise TotpRequiredError()

        # Raises InvalidTotpError on a bad code or on one outside the window.
        counter = self._totp.verify(user.totp_secret, code, user.totp_last_counter)

        # The replay check is the UPDATE, not a comparison here. Two requests
        # carrying the same code would both read the same prior counter, both
        # pass a Python check, and both be admitted; only one can win a
        # conditional write. This is what makes a code observed in a phishing
        # proxy useless for a second login inside its window.
        if not await self._users.advance_totp_counter(user.id, counter):
            raise InvalidTotpError(detail=f"replayed counter={counter} user={user.id}")

        return user
