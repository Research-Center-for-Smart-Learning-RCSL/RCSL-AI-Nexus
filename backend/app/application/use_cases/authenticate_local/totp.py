"""Totp authentication step."""

from __future__ import annotations

from app.application.audit_subject import subject_for
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidTotpError,
    RateLimitedError,
)

from .password import PasswordStep


class TotpStep(PasswordStep):
    async def verify_totp(self, user_id: str, code: str, *, client_ip: str) -> User:
        user, totp_secret = await self._require_second_step_user(user_id, client_ip=client_ip)
        subject = subject_for(user)

        try:
            await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(user.login, client_ip=client_ip, step="totp")
            raise

        try:
            # Raises InvalidTotpError on a bad code or on one outside the window.
            counter = self._totp.verify(
                self._secret_box.decrypt(totp_secret), code, user.totp_last_counter
            )
        except InvalidTotpError:
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            await self._fail(subject, client_ip=client_ip, reason="bad_totp_code")
            raise

        # The replay check is the UPDATE, not a comparison here. Two requests
        # carrying the same code would both read the same prior counter, both
        # pass a Python check, and both be admitted; only one can win a
        # conditional write. This is what makes a code observed in a phishing
        # proxy useless for a second login inside its window.
        if not await self._users.advance_totp_counter(user.id, counter):
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            # Distinguished from a wrong code on purpose: this one means a
            # second request presented the same code at the same moment. A
            # *sequential* replay never reaches here — `totp.verify` rejects a
            # counter at or below the stored one and reports `bad_totp_code`,
            # which by then it is. Worth knowing when reading the log, because
            # the reasons do not partition the way their names suggest.
            await self._fail(subject, client_ip=client_ip, reason="totp_replay")
            raise InvalidTotpError(detail=f"replayed counter={counter} user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)
        await self._signed_in(subject, client_ip=client_ip, factor="totp")
        return user
