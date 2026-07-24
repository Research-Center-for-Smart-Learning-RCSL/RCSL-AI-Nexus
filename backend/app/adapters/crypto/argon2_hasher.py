"""argon2id password hashing.

Two properties here are not library defaults and are the reason this adapter
exists rather than a call to `PasswordHasher` at the use case.

**Hashing runs in a worker thread**, which is why `PasswordHasherPort` is
async. At these parameters a single hash occupies a core for tens of
milliseconds. The login endpoint is unauthenticated and sits behind no edge
protection (docs/architecture/security.md section 15.2), so performing that
work on the event loop hands an attacker a cheap way to stall every other
request in the process, including the ones that would have rate limited them.

**Thread concurrency is capped.** anyio's default limiter permits 40 threads.
At 64 MiB of working memory per hash that is 2.5 GB reachable from an
unauthenticated endpoint, which trades a CPU stall for an out-of-memory kill.
The semaphore below bounds it.
"""

from __future__ import annotations

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

DUMMY_PASSWORD = "argon2-dummy-verify-target"  # noqa: S105  (not a credential)

MEMORY_COST_KIB = 64 * 1024
TIME_COST = 3
PARALLELISM = 4
"""RFC 9106's second recommended parameter set (64 MiB, t=3, p=4). The first
set asks for 2 GiB, which on a machine whose whole purpose is holding models
in unified memory is the wrong thing to spend on a login."""

MAX_CONCURRENT_HASHES = 4
"""Bounds resident memory at roughly 256 MiB. Deliberately small: this is a
platform for a research group, not a consumer service, and a login queueing
briefly under attack is preferable to the box swapping."""


class Argon2Hasher:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            memory_cost=MEMORY_COST_KIB,
            time_cost=TIME_COST,
            parallelism=PARALLELISM,
        )
        self._limiter = anyio.Semaphore(MAX_CONCURRENT_HASHES)

        self._dummy_hash = self._hasher.hash(DUMMY_PASSWORD)
        """Computed with the same parameters as real hashes, at construction
        rather than as a constant, so that changing the cost above cannot leave
        the enumeration defence burning a visibly different amount of time."""

    async def hash(self, password: str) -> str:
        async with self._limiter:
            return await anyio.to_thread.run_sync(self._hasher.hash, password)

    async def verify(self, password: str, password_hash: str) -> bool:
        async with self._limiter:
            return await anyio.to_thread.run_sync(self._verify_sync, password, password_hash)

    async def dummy_verify(self) -> None:
        async with self._limiter:
            await anyio.to_thread.run_sync(self._verify_sync, DUMMY_PASSWORD, self._dummy_hash)

    def _verify_sync(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError):
            # A malformed or truncated stored hash. Returning False rather than
            # propagating keeps a corrupted row indistinguishable from a wrong
            # password to the caller; the row still needs an operator, but that
            # is not something the login response should announce.
            return False
