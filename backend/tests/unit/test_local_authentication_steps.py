from __future__ import annotations

import pyotp
import pytest

from app.domain.entities.invitation import RecoveryCode
from app.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTotpError,
    RateLimitedError,
)
from app.domain.services.token_service import TokenService
from tests.unit.authenticate_local_fixtures import (
    IP,
    NOW,
    SECRET,
    build,
    make_user,
)
from tests.unit.fakes import FakeInvitations, FakeUsers

pytest_plugins = ("tests.unit.authenticate_local_fixtures",)


async def test_unknown_login_still_burns_a_hash() -> None:
    """Without this, response timing separates real accounts from invented
    ones and the identical error message achieves nothing."""
    use_case, hasher, _ = build(FakeUsers())

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password("nobody@example.org", "whatever", client_ip=IP)

    assert hasher.dummy_calls == 1


async def test_incomplete_account_is_indistinguishable_from_a_wrong_password() -> None:
    """An invited user who never enrolled has a row but no credentials.
    Reporting that differently would let anyone probe which invitations are
    outstanding."""
    users = FakeUsers([make_user(password_hash=None, totp_secret=None)])
    use_case, hasher, _ = build(users)

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password("someone@example.org", "anything", client_ip=IP)

    assert hasher.dummy_calls == 1


async def test_disabled_account_cannot_sign_in() -> None:
    users = FakeUsers([make_user(disabled_at=NOW)])
    use_case, _, _ = build(users)

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password(
            "someone@example.org", "correct horse battery staple", client_ip=IP
        )


async def test_correct_password_yields_a_challenge_not_a_session() -> None:
    users = FakeUsers([make_user()])
    use_case, _, _ = build(users)

    result = await use_case.verify_password(
        "someone@example.org", "correct horse battery staple", client_ip=IP
    )

    assert result.user_id == "u1"


async def test_repeated_failures_are_refused_before_any_hashing() -> None:
    """The ordering is the control. A limiter that ran after the hash would
    still return 429 while having already spent the CPU it exists to protect."""
    users = FakeUsers([make_user()])
    use_case, hasher, _ = build(users)

    for _ in range(6):
        with pytest.raises(InvalidCredentialsError):
            await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    hashes_before = hasher.dummy_calls
    with pytest.raises(RateLimitedError):
        await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    assert hasher.dummy_calls == hashes_before


async def test_totp_counter_cannot_be_replayed() -> None:
    """A code observed in a phishing proxy stays valid for its whole 30 second
    window unless the accepted counter is claimed. The second attempt uses the
    same code, which is exactly what an interceptor would present."""
    users = FakeUsers([make_user()])
    use_case, _, _ = build(users)
    current = pyotp.TOTP(SECRET).now()

    await use_case.verify_totp("u1", current, client_ip=IP)

    with pytest.raises(InvalidTotpError):
        await use_case.verify_totp("u1", current, client_ip=IP)


async def test_recovery_code_is_single_use() -> None:
    tokens = TokenService()
    issued = tokens.issue_recovery_codes(count=2)

    invitations = FakeInvitations()
    await invitations.save_recovery_codes(
        [
            RecoveryCode(id=f"c{i}", user_id="u1", code_hash=code.hashed)
            for i, code in enumerate(issued)
        ]
    )

    users = FakeUsers([make_user()])
    use_case, _, _ = build(users, invitations)

    await use_case.verify_recovery_code("u1", issued[0].plaintext, client_ip=IP)

    with pytest.raises(InvalidTotpError):
        await use_case.verify_recovery_code("u1", issued[0].plaintext, client_ip=IP)

    # The second code is untouched: consuming one must not invalidate the set.
    await use_case.verify_recovery_code("u1", issued[1].plaintext, client_ip=IP)


async def test_recovery_code_matches_regardless_of_formatting() -> None:
    """People retype these from a screen or from paper. Separators and case
    are presentation, not part of the secret."""
    tokens = TokenService()
    issued = tokens.issue_recovery_codes(count=1)

    invitations = FakeInvitations()
    await invitations.save_recovery_codes(
        [RecoveryCode(id="c0", user_id="u1", code_hash=issued[0].hashed)]
    )

    use_case, _, _ = build(FakeUsers([make_user()]), invitations)

    mangled = issued[0].plaintext.replace("-", " ").upper()
    await use_case.verify_recovery_code("u1", mangled, client_ip=IP)
