"""Password authentication step."""

from __future__ import annotations

from app.application.audit_subject import subject_for, unknown_subject
from app.domain.exceptions import (
    InvalidCredentialsError,
    RateLimitedError,
)

from .coordination import AuthenticationCoordination
from .results import PasswordResult


class PasswordStep(AuthenticationCoordination):
    async def verify_password(self, login: str, password: str, *, client_ip: str) -> PasswordResult:
        # Before the hash, not after. See LoginThrottle.assert_allowed.
        try:
            await self._throttle.assert_allowed(login=login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(login, client_ip=client_ip, step="password")
            raise

        user = await self._users.get_by_login(login)

        if user is None:
            # Burn comparable time before failing, so response latency does
            # not distinguish an unknown login from a wrong password. Without
            # this, timing enumerates valid accounts.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(unknown_subject(login), client_ip=client_ip, reason="unknown_login")
            raise InvalidCredentialsError(detail=f"unknown login={login}")

        if user.disabled_at is not None:
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="account_disabled")
            raise InvalidCredentialsError(detail=f"disabled user={user.id}")

        if not user.can_use_public_entrance:
            # Tailnet-only account, or an invitation that was never completed.
            # Same error as above: whether an account has local credentials is
            # not something an unauthenticated caller should be able to probe.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="no_local_credentials")
            raise InvalidCredentialsError(detail=f"no local credentials user={user.id}")

        # Implied by can_use_public_entrance above, but bound to a local so the
        # narrowing survives without an `assert`, which python -O would strip.
        password_hash = user.password_hash
        if password_hash is None or not await self._hasher.verify(password, password_hash):
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="bad_password")
            raise InvalidCredentialsError(detail=f"bad password user={user.id}")

        # Deliberately not cleared here. The counters are cleared only once the
        # second factor has also succeeded, so a valid password alone cannot be
        # used to reset the limiter and grind at the TOTP step indefinitely.
        #
        # Nothing is audited on this path either, and for the same reason: a
        # correct password is not a sign-in. The event section 12 asks for is
        # the one that produces a session, and that is the second step.
        return PasswordResult(user_id=user.id)
