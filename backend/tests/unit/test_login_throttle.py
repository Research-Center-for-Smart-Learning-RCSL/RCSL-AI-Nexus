"""The throttle must never become the attack it defends against.

The first version did, twice: it could lock a named account out from its
owner's own address, and a single valid account could wipe the per-address
counter at will. Both are pinned here because both looked correct.
"""

from __future__ import annotations

import pytest

from app.adapters.cache.redis_adapter import InMemoryCache
from app.domain.exceptions import RateLimitedError
from app.domain.services.login_throttle import (
    FREE_ATTEMPTS,
    IP_FREE_ATTEMPTS,
    LoginThrottle,
)

ADMIN = "admin@example.org"
ATTACKER_IP = "6.6.6.6"
OWNER_IP = "203.0.113.9"


def build() -> LoginThrottle:
    return LoginThrottle(InMemoryCache())


async def test_a_named_account_cannot_be_locked_out_from_another_address() -> None:
    """The defect security.md 5.3 exists to prevent: failures against a login
    from one address must not bar that login's owner from their own."""
    throttle = build()
    for _ in range(FREE_ATTEMPTS + 5):
        await throttle.record_failure(login=ADMIN, client_ip=ATTACKER_IP)

    # The owner, from their own machine, is unaffected.
    await throttle.assert_allowed(login=ADMIN, client_ip=OWNER_IP)


async def test_one_address_grinding_one_account_is_refused() -> None:
    throttle = build()
    for _ in range(FREE_ATTEMPTS + 1):
        await throttle.record_failure(login=ADMIN, client_ip=ATTACKER_IP)

    with pytest.raises(RateLimitedError):
        await throttle.assert_allowed(login=ADMIN, client_ip=ATTACKER_IP)


async def test_one_address_working_through_many_logins_is_refused() -> None:
    """The per-address counter catches this. One failure per distinct login,
    so the pair counter never blocks and the address counter is what trips."""
    throttle = build()
    for i in range(IP_FREE_ATTEMPTS + 1):
        await throttle.record_failure(login=f"victim{i}@example.org", client_ip=ATTACKER_IP)

    with pytest.raises(RateLimitedError):
        await throttle.assert_allowed(login="victim0@example.org", client_ip=ATTACKER_IP)


async def test_a_successful_login_does_not_clear_the_per_address_counter() -> None:
    """The reset bug: spray failures, sign in to your own account from the same
    address, and the per-address counter that was catching you is gone."""
    throttle = build()
    for i in range(IP_FREE_ATTEMPTS + 1):
        await throttle.record_failure(login=f"victim{i}@example.org", client_ip=ATTACKER_IP)

    # The attacker signs in to an account they legitimately hold, same address.
    await throttle.clear(login="attacker-own@example.org", client_ip=ATTACKER_IP)

    # The per-address grind is still blocked.
    with pytest.raises(RateLimitedError):
        await throttle.assert_allowed(login="victim0@example.org", client_ip=ATTACKER_IP)


async def test_clearing_lets_the_owner_back_in_after_their_own_mistakes() -> None:
    """A success from the same address clears that address+account pair, so a
    user who fat-fingered their password a few times is not then penalised."""
    throttle = build()
    for _ in range(FREE_ATTEMPTS + 1):
        await throttle.record_failure(login=ADMIN, client_ip=OWNER_IP)

    await throttle.clear(login=ADMIN, client_ip=OWNER_IP)

    await throttle.assert_allowed(login=ADMIN, client_ip=OWNER_IP)
