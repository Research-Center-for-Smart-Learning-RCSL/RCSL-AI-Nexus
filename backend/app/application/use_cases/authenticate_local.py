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

        # Raises InvalidTotpError on a bad code or on replay of a counter at
        # or below the last accepted one.
        counter = self._totp.verify(user.totp_secret, code, user.totp_last_counter)

        if user.totp_last_counter is not None and counter <= user.totp_last_counter:
            raise InvalidTotpError(detail=f"replayed counter={counter} user={user.id}")

        await self._users.save(replace_counter(user, counter))
        return user


def replace_counter(user: User, counter: int) -> User:
    from dataclasses import replace

    return replace(user, totp_last_counter=counter)
