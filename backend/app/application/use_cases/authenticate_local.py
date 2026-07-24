"""Password then TOTP authentication for the public entrance.

This is a use case rather than middleware logic because it carries real
rules that deserve unit tests: enumeration resistance, TOTP replay
rejection, and the refusal to authenticate an account whose second factor
was never enrolled. See docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest

from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTotpError,
    TotpRequiredError,
)
from app.domain.ports.repositories import InvitationRepositoryPort, UserRepositoryPort
from app.domain.ports.security_ports import PasswordHasherPort, SecretBoxPort, TotpPort
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.token_service import TokenService
from app.shared.clock import Clock


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
        *,
        invitations: InvitationRepositoryPort,
        tokens: TokenService,
        throttle: LoginThrottle,
        secret_box: SecretBoxPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._totp = totp
        self._invitations = invitations
        self._tokens = tokens
        self._throttle = throttle
        self._secret_box = secret_box
        self._clock = clock

    async def verify_password(self, login: str, password: str, *, client_ip: str) -> PasswordResult:
        # Before the hash, not after. See LoginThrottle.assert_allowed.
        await self._throttle.assert_allowed(login=login, client_ip=client_ip)

        user = await self._users.get_by_login(login)

        if user is None:
            # Burn comparable time before failing, so response latency does
            # not distinguish an unknown login from a wrong password. Without
            # this, timing enumerates valid accounts.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            raise InvalidCredentialsError(detail=f"unknown login={login}")

        if user.disabled_at is not None:
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            raise InvalidCredentialsError(detail=f"disabled user={user.id}")

        if not user.can_use_public_entrance:
            # Tailnet-only account, or an invitation that was never completed.
            # Same error as above: whether an account has local credentials is
            # not something an unauthenticated caller should be able to probe.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            raise InvalidCredentialsError(detail=f"no local credentials user={user.id}")

        # Implied by can_use_public_entrance above, but bound to a local so the
        # narrowing survives without an `assert`, which python -O would strip.
        password_hash = user.password_hash
        if password_hash is None or not await self._hasher.verify(password, password_hash):
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            raise InvalidCredentialsError(detail=f"bad password user={user.id}")

        # Deliberately not cleared here. The counters are cleared only once the
        # second factor has also succeeded, so a valid password alone cannot be
        # used to reset the limiter and grind at the TOTP step indefinitely.
        return PasswordResult(user_id=user.id)

    async def verify_totp(self, user_id: str, code: str, *, client_ip: str) -> User:
        user = await self._users.get(user_id)
        if user is None or user.totp_secret is None:
            raise TotpRequiredError()

        await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)

        try:
            # Raises InvalidTotpError on a bad code or on one outside the window.
            counter = self._totp.verify(
                self._secret_box.decrypt(user.totp_secret), code, user.totp_last_counter
            )
        except InvalidTotpError:
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            raise

        # The replay check is the UPDATE, not a comparison here. Two requests
        # carrying the same code would both read the same prior counter, both
        # pass a Python check, and both be admitted; only one can win a
        # conditional write. This is what makes a code observed in a phishing
        # proxy useless for a second login inside its window.
        if not await self._users.advance_totp_counter(user.id, counter):
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            raise InvalidTotpError(detail=f"replayed counter={counter} user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)
        return user

    async def verify_recovery_code(self, user_id: str, presented: str, *, client_ip: str) -> User:
        """Second-step alternative when the authenticator is lost.

        A recovery code bypasses the second factor outright, so it is checked
        by digest comparison against the stored hashes and claimed with the
        same conditional UPDATE the TOTP counter uses. Nothing here reveals how
        many codes remain; that belongs to an authenticated view of the
        account, not to the login screen.
        """
        user = await self._users.get(user_id)
        if user is None:
            raise TotpRequiredError()

        await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)

        digest = self._tokens.hash_recovery_code(presented)
        stored = await self._invitations.list_recovery_codes(user.id)

        claimed = False
        for candidate in stored:
            if candidate.used_at is not None:
                continue
            if not compare_digest(candidate.code_hash, digest):
                continue
            claimed = await self._invitations.consume_recovery_code(candidate.id, self._clock.now())
            break

        if not claimed:
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            raise InvalidTotpError(detail=f"no unused recovery code matched user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)
        return user
