"""Where a TOTP secret lives between being generated and being proved.

Enrolment always spans two calls: one produces the QR, the other verifies a
code from the authenticator that scanned it. Both must see the same secret.

**It cannot be parked in the user row.** `users` carries a check constraint
that `password_hash` and `totp_secret` are null together, so an account never
exists in a password-only state. Writing a secret for an invitation that has
not chosen a password yet violates it, which is the constraint doing its job:
a half-finished enrolment is not an account.

So the candidate is held in the cache, encrypted, with a short lifetime. Three
properties follow, and all three are wanted:

- Abandoning the flow leaves the existing authenticator untouched, which
  matters most for re-enrolment, where the user still has a working one.
- The window in which a generated-but-unproved secret exists anywhere is
  minutes, not the 72 hours an invitation lasts.
- Expiry is recoverable: reloading the page calls `begin` again and produces a
  fresh QR, so the failure mode is a re-scan rather than a dead link.
"""

from __future__ import annotations

from app.domain.exceptions import TotpEnrolmentExpiredError
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.ports.security_ports import SecretBoxPort

KEY_PREFIX = "totp_enrol:"


class PendingEnrolment:
    def __init__(self, cache: CachePort, secret_box: SecretBoxPort, *, ttl_seconds: int) -> None:
        self._cache = cache
        self._secret_box = secret_box
        self._ttl = ttl_seconds

    async def put(self, user_id: str, secret: str) -> None:
        await self._cache.set(
            _key(user_id), self._secret_box.encrypt(secret), ttl_seconds=self._ttl
        )

    async def get(self, user_id: str) -> str | None:
        stored = await self._cache.get(_key(user_id))
        return None if stored is None else self._secret_box.decrypt(stored)

    async def require(self, user_id: str) -> str:
        secret = await self.get(user_id)
        if secret is None:
            raise TotpEnrolmentExpiredError(detail=f"no pending enrolment user={user_id}")
        return secret

    async def clear(self, user_id: str) -> None:
        await self._cache.delete(_key(user_id))


def _key(user_id: str) -> str:
    return f"{KEY_PREFIX}{user_id}"
