"""Regressions for the lower-severity findings from the adversarial review.

Grouped because each is small and independent: a CSRF cookie edge case, a
non-ASCII header, a challenge that outlived a disable, the scopes a `user`
should and should not hold, and the human-account role constraint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
import pytest
from pydantic import ValidationError

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.domain.entities.actor import Role, Scope
from app.domain.entities.user import User
from app.domain.exceptions import TotpRequiredError
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.token_service import TokenService
from app.interfaces.http.schemas.admin_schemas import CreateUserRequest
from app.shared.clock import FixedClock
from tests.unit.fakes import FakeAudit, FakeHasher, FakeInvitations, FakeSecretBox, FakeUsers

NOW = datetime(2026, 7, 25, tzinfo=UTC)
SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105


# --- CSRF comparison tolerates a non-ASCII header ------------------------


def test_the_csrf_comparison_does_not_raise_on_a_non_ascii_header() -> None:
    """Starlette decodes headers as latin-1, so a value with a byte above 0x7f
    reaches the comparison as a str with a non-ASCII codepoint. `compare_digest`
    refuses that with TypeError, which uncaught became a 500 and defeated the
    deliberate 403. The helper compares utf-8 encodings instead."""
    from app.interfaces.http.middleware.csrf import _tokens_match

    # A legitimate token is url-safe base64, hence ASCII, and still matches.
    assert _tokens_match("abc-123_XYZ", "abc-123_XYZ") is True
    # A non-ASCII header returns False rather than raising.
    assert _tokens_match("café-\xe9", "abc-123_XYZ") is False


# --- role scopes ---------------------------------------------------------


def test_a_user_holds_only_the_scopes_5_2_grants() -> None:
    """Use the chat UI, manage their own keys, view their own usage. The read
    scopes for models, routing and nodes were an over-grant that let a user
    enumerate the registry and read the node's tailnet address.

    **`prompt:read` was added on 2026-08-05 and is the only widening this
    assertion has admitted.** It is here rather than passed over in silence
    because the set is pinned exactly on purpose: anything added has to be
    argued for in this docstring, and a future one that is not still fails.

    Two reasons it does not reopen what the withheld reads opened. It names no
    infrastructure — a template is text this tenant authored, so listing them
    reveals nothing about models, nodes or addresses, and the repository is
    tenant-scoped so it cannot reach another tenant's. And selecting a template
    is *part of* using the chat: a member who cannot see which exist cannot
    choose one, and the alternative is being told a name out of band and
    guessing. The transparency runs the same way — a template shapes every
    answer the member receives, so being able to read the one applied on their
    behalf is a property worth having rather than a leak.
    """
    scopes = RoleAuthorization().scopes_for("user")

    assert scopes == frozenset(
        {
            Scope.CHAT_USE,
            Scope.API_KEY_READ_OWN,
            Scope.API_KEY_WRITE_OWN,
            Scope.USAGE_READ_OWN,
            Scope.PROMPT_READ,
        }
    )
    for absent in (Scope.MODEL_READ, Scope.ROUTING_READ, Scope.NODE_READ):
        assert absent not in scopes
    # Reading a template is not authoring one; that stays with the roles that
    # hold the knowledge base.
    assert Scope.PROMPT_WRITE not in scopes


def test_a_service_key_reaches_no_control_plane_scope() -> None:
    scopes = RoleAuthorization().scopes_for("service")
    assert scopes == frozenset({Scope.CHAT_USE, Scope.USAGE_READ_OWN})


# --- human-account role --------------------------------------------------


def test_a_human_account_cannot_be_created_in_the_service_role() -> None:
    """SERVICE exists for API keys; its scopes were designed for a machine."""
    with pytest.raises(ValidationError):
        CreateUserRequest(login="x@example.org", display_name="X", role="service")

    # The two human roles are accepted.
    assert (
        CreateUserRequest(login="a@example.org", display_name="A", role="admin").role is Role.ADMIN
    )
    assert CreateUserRequest(login="u@example.org", display_name="U", role="user").role is Role.USER


# --- challenge outliving a disable ---------------------------------------


def _auth(users: FakeUsers) -> AuthenticateLocal:
    return AuthenticateLocal(
        users=users,
        hasher=FakeHasher(),
        totp=PyotpTotp(),
        invitations=FakeInvitations(),
        tokens=TokenService(),
        throttle=LoginThrottle(InMemoryCache()),
        secret_box=FakeSecretBox(),
        audit=FakeAudit(),
        clock=FixedClock(NOW),
    )


async def test_a_disabled_account_cannot_complete_the_second_step() -> None:
    """The challenge lasts minutes; a disable inside that window must take
    effect at step two, not only on the next request."""
    user = User(
        id="u1",
        login="u@example.org",
        display_name="U",
        role=Role.USER,
        password_hash="hashed:pw",  # noqa: S106
        totp_secret=f"enc:{SECRET}",
        disabled_at=NOW,
    )
    auth = _auth(FakeUsers([user]))

    with pytest.raises(TotpRequiredError):
        await auth.verify_totp("u1", pyotp.TOTP(SECRET).now(), client_ip="1.2.3.4")
