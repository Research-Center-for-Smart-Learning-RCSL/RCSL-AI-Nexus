"""Recovery authentication step."""

from __future__ import annotations

from hmac import compare_digest

from app.application.audit_subject import subject_for
from app.domain.entities.audit import AuditAction
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidTotpError,
    RateLimitedError,
)

from .totp import TotpStep


class RecoveryCodeStep(TotpStep):
    async def verify_recovery_code(self, user_id: str, presented: str, *, client_ip: str) -> User:
        """Second-step alternative when the authenticator is lost.

        A recovery code bypasses the second factor outright, so it is checked
        by digest comparison against the stored hashes and claimed with the
        same conditional UPDATE the TOTP counter uses. Nothing here reveals how
        many codes remain; that belongs to an authenticated view of the
        account, not to the login screen.
        """
        user, _ = await self._require_second_step_user(user_id, client_ip=client_ip)
        subject = subject_for(user)

        try:
            await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(user.login, client_ip=client_ip, step="recovery_code")
            raise

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
            await self._fail(subject, client_ip=client_ip, reason="no_recovery_code_matched")
            raise InvalidTotpError(detail=f"no unused recovery code matched user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)

        # Two rows, not one, and the second is not redundant. `user.signed_in`
        # says a session was granted; this says a single-use credential was
        # spent, which is a fact about the account's recovery state rather than
        # about this login. Counting them answers "how many codes are gone"
        # without reading inside anyone's `detail`, and section 12 names
        # recovery code use as its own event for the same reason: bypassing the
        # second factor is worth seeing without knowing to look for it.
        await self._audit.record(subject, AuditAction.USER_RECOVERY_CODE_USED, target=user.id)
        await self._signed_in(subject, client_ip=client_ip, factor="recovery_code")
        return user
