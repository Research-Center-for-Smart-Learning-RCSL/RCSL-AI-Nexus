"""Escalating rejection for repeated login failures.

**Nothing here can lock a named account out.** That is the whole design, and
the first version got it wrong: it counted failures per login and refused on
that count alone, so six requests naming an administrator kept the real
administrator out from their own machine, indefinitely, for about 0.4 requests
per minute. security.md section 5.3 says hard lockout is "deliberately
avoided" because "it converts a known login into a denial-of-service lever
against a real person" — and that was exactly the lever.

So the counters that can *refuse* are keyed on something the attacker has to
spend to vary, and at two thresholds:

- `ip+account` — one address grinding one account. Trips at `FREE_ATTEMPTS`,
  and a success from that address clears it, so a user who mistyped their own
  password a few times is not then penalised once they get it right.
- `ip` — one address working through many logins. Trips at a *higher* count,
  and a success never clears it. The higher threshold is what keeps a single
  account's failures from reaching it: once the pair counter blocks at five,
  no further failure for that account is recorded, so one legitimate user
  fumbling their own login cannot push the shared per-address counter up.

The per-account counter still exists and is still incremented, but it only
raises an alert. A distributed attack on one login is visible in it without
being able to bar the owner.

**The delay is returned, not slept.** Holding the request open for the penalty
would consume a worker per attacker, which is a denial of service implemented
by the defence. The caller gets 429 with `Retry-After`, and that value is the
remaining window rather than a smaller number that invites an immediate retry.
"""

from __future__ import annotations

import hashlib
import logging

from app.domain.exceptions import RateLimitedError
from app.domain.ports.infrastructure_ports import CachePort

logger = logging.getLogger(__name__)

FREE_ATTEMPTS = 5
"""Failures for one address against one account before it is refused."""

IP_FREE_ATTEMPTS = 30
"""Failures for one address across all accounts before it is refused. Higher
than the pair limit, because it aggregates, and a single account's failures
stop being recorded once the pair counter blocks at five."""

WINDOW_SECONDS = 900
ALERT_AFTER_ACCOUNT_FAILURES = 20
"""Distributed grinding on one login. Logged, never refused."""


class LoginThrottle:
    def __init__(
        self,
        cache: CachePort,
        *,
        free_attempts: int = FREE_ATTEMPTS,
        ip_free_attempts: int = IP_FREE_ATTEMPTS,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self._cache = cache
        self._free = free_attempts
        self._ip_free = ip_free_attempts
        self._window = window_seconds

    async def assert_allowed(self, *, login: str, client_ip: str) -> None:
        """Called before any hashing.

        Ordering is the point: argon2 is the expensive part, so a check that
        ran after it would let an attacker impose the cost they are being
        limited for.
        """
        limits = (
            (self._ip_key(client_ip), self._ip_free),
            (self._pair_key(login=login, client_ip=client_ip), self._free),
        )
        for key, ceiling in limits:
            failures = int(await self._cache.get(key) or 0)
            if failures > ceiling:
                # The window, not a smaller escalating number. The counter's
                # TTL runs from the first failure, so advertising 30 seconds
                # invited a retry that was always going to be refused.
                raise RateLimitedError(retry_after_seconds=self._window)

    async def record_failure(self, *, login: str, client_ip: str) -> None:
        await self._cache.incr(self._ip_key(client_ip), ttl_seconds=self._window)
        await self._cache.incr(
            self._pair_key(login=login, client_ip=client_ip), ttl_seconds=self._window
        )

        # Counted but never enforced. See the module docstring.
        per_account = await self._cache.incr(self._account_key(login), ttl_seconds=self._window)
        if per_account == ALERT_AFTER_ACCOUNT_FAILURES:
            logger.warning(
                "login_failures_concentrated_on_one_account count=%s window=%ss "
                "(not refused: refusing on this counter would lock the owner out)",
                per_account,
                self._window,
            )

    async def clear(self, *, login: str, client_ip: str) -> None:
        """A successful login clears only what that success speaks for.

        The per-address counter is deliberately **not** cleared. It was, and
        that handed an attacker holding any one valid account a way to reset
        it at will: spray wrong passwords across several victims, sign in to
        their own account from the same address, repeat forever. The counter
        that exists to catch one address working through a list of logins was
        erasable by anyone on that list.
        """
        await self._cache.delete(self._pair_key(login=login, client_ip=client_ip))
        await self._cache.delete(self._account_key(login))

    def _ip_key(self, client_ip: str) -> str:
        return f"login_fail:ip:{client_ip}"

    def _pair_key(self, *, login: str, client_ip: str) -> str:
        return f"login_fail:pair:{client_ip}:{_digest(login)}"

    def _account_key(self, login: str) -> str:
        return f"login_fail:account:{_digest(login)}"


def _digest(login: str) -> str:
    """Hashed rather than stored, so the cache does not accumulate a list of
    valid email addresses that anyone with read access to Redis could lift."""
    return hashlib.sha256(login.strip().lower().encode()).hexdigest()[:32]
