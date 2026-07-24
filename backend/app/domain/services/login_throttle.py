"""Escalating rejection for repeated login failures.

**Not a lockout.** Locking an account after N failures converts a known login
into a denial-of-service lever against a real person, which on a platform with
a handful of administrators means one of them can be kept out at will. Delay
that grows with the failure count achieves the defensive goal without handing
anyone that lever. See docs/architecture/security.md section 5.3.

**The delay is returned, not slept.** Holding the request open for the penalty
would consume a worker per attacker, which is a denial of service implemented
by the defence. The caller gets 429 with `Retry-After`.

Counted twice, by source address and by account, because either alone has a
gap: per-address misses a distributed attempt against one account, and
per-account misses one address working through a list of logins.
"""

from __future__ import annotations

import hashlib

from app.domain.exceptions import RateLimitedError
from app.domain.ports.infrastructure_ports import CachePort

FREE_ATTEMPTS = 5
WINDOW_SECONDS = 900
BASE_DELAY_SECONDS = 30
MAX_DELAY_SECONDS = 900


class LoginThrottle:
    def __init__(
        self,
        cache: CachePort,
        *,
        free_attempts: int = FREE_ATTEMPTS,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self._cache = cache
        self._free = free_attempts
        self._window = window_seconds

    async def assert_allowed(self, *, login: str, client_ip: str) -> None:
        """Called before any hashing.

        Ordering is the point: argon2 is the expensive part, so a check that
        ran after it would let an attacker impose the cost they are being
        limited for.
        """
        for key in self._keys(login=login, client_ip=client_ip):
            failures = int(await self._cache.get(key) or 0)
            if failures > self._free:
                raise RateLimitedError(retry_after_seconds=self._delay_for(failures))

    async def record_failure(self, *, login: str, client_ip: str) -> None:
        for key in self._keys(login=login, client_ip=client_ip):
            await self._cache.incr(key, ttl_seconds=self._window)

    async def clear(self, *, login: str, client_ip: str) -> None:
        """A successful login clears both counters.

        Without this, someone who mistypes their password several times a day
        accumulates a penalty they never triggered in a single sitting.
        """
        for key in self._keys(login=login, client_ip=client_ip):
            await self._cache.delete(key)

    def _keys(self, *, login: str, client_ip: str) -> tuple[str, str]:
        # The login is hashed rather than stored, so the cache does not
        # accumulate a list of valid email addresses that anyone with read
        # access to Redis could lift.
        digest = hashlib.sha256(login.strip().lower().encode()).hexdigest()[:32]
        return (f"login_fail:ip:{client_ip}", f"login_fail:account:{digest}")

    def _delay_for(self, failures: int) -> int:
        over = failures - self._free
        return int(min(BASE_DELAY_SECONDS * (2 ** (over - 1)), MAX_DELAY_SECONDS))
