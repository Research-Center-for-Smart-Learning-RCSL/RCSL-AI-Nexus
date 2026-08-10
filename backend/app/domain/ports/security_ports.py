"""Ports for credential handling, authorization, and auditing.

Password hashing and TOTP live behind ports so that argon2 and pyotp stay in
adapters: the domain must remain importable and testable without them, and
the parameters are tuned in one place.

`AuthorizationPort` and `AuditPort` are ports rather than helper functions so
that "every administrative action is authorized and audited" is enforced by
the shape of the code rather than by remembering to call something.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction


class PasswordHasherPort(Protocol):
    """Async because argon2 is deliberately expensive.

    A hash occupies a core for tens of milliseconds, and the endpoint that
    triggers it is unauthenticated and behind no edge protection. A synchronous
    port would force that work onto the event loop, where a handful of
    concurrent attempts stalls every other request in the process. The cost is
    described where it is paid, in adapters/crypto/argon2_hasher.py.
    """

    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, password_hash: str) -> bool: ...

    async def dummy_verify(self) -> None:
        """Burn roughly the same time as a real verification.

        Called when no user matches a login, so that an unknown account and a
        wrong password are indistinguishable by timing as well as by response
        body. Without this, login response times enumerate valid accounts.
        """
        ...


class PasswordPolicyPort(Protocol):
    """Strength checking, kept out of the domain for the same reason as
    hashing: the estimator ships a large frequency dictionary and is a library
    choice, not a rule of this platform.

    The rule that *is* this platform's is in the adapter's docstring, and it
    must stay identical to what the frontend enforces. A backend that rejects
    what the form accepted produces an error the user cannot act on.
    """

    def assert_acceptable(self, password: str, *, user_inputs: Sequence[str] = ()) -> None:
        """Raise `WeakPasswordError`, whose `reason` is shown to the user.

        `user_inputs` carries the login and display name so that a password
        built out of them scores as the guess it is.
        """
        ...


class TotpPort(Protocol):
    def generate_secret(self) -> str: ...

    def provisioning_uri(self, secret: str, login: str, issuer: str) -> str:
        """otpauth:// URI rendered as a QR code during enrolment."""
        ...

    def verify(self, secret: str, code: str, last_counter: int | None) -> int:
        """Return the accepted time counter, or raise `InvalidTotpError`.

        Rejects any counter at or below `last_counter`. Without that check a
        code observed in a phishing proxy stays valid for its whole window,
        which defeats the point of the second factor.
        """
        ...


class SecretBoxPort(Protocol):
    """Symmetric encryption for values that must survive a database read.

    Used for the TOTP secret, which unlike a password is a bearer credential
    that ordinary use never rotates: a leaked `users` table would otherwise
    defeat the second factor while argon2 still protected the first.
    """

    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class SessionRegistryPort(Protocol):
    """The part of session handling that use cases need.

    Deliberately only the invalidation half. Creating and reading sessions is
    the entrance's business, but *ending* them is a consequence of domain
    events — a password changed, an account disabled — and putting it in the
    router would mean every future caller of those use cases has to remember
    it. Neither method returns anything, so a use case cannot start reasoning
    about sessions it should not know exist.
    """

    async def invalidate_all(self, user_id: str, now: datetime) -> None: ...

    async def invalidate_others(
        self, user_id: str, keep_session_id: str, now: datetime
    ) -> None: ...


class AuthorizationPort(Protocol):
    def require(self, actor: Actor, scope: Scope) -> None:
        """Raise `NotAuthorizedError` unless the actor holds the scope."""
        ...

    def scopes_for(self, actor_role: str) -> frozenset[Scope]: ...


class AuditPort(Protocol):
    async def record(
        self,
        actor: Actor,
        action: AuditAction,
        *,
        target: str | None = None,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None: ...
