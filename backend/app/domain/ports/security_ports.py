"""Ports for credential handling, authorization, and auditing.

Password hashing and TOTP live behind ports so that argon2 and pyotp stay in
adapters: the domain must remain importable and testable without them, and
the parameters are tuned in one place.

`AuthorizationPort` and `AuditPort` are ports rather than helper functions so
that "every administrative action is authorized and audited" is enforced by
the shape of the code rather than by remembering to call something.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.actor import Actor, Scope


class PasswordHasherPort(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...

    def dummy_verify(self) -> None:
        """Burn roughly the same time as a real verification.

        Called when no user matches a login, so that an unknown account and a
        wrong password are indistinguishable by timing as well as by response
        body. Without this, login response times enumerate valid accounts.
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


class AuthorizationPort(Protocol):
    def require(self, actor: Actor, scope: Scope) -> None:
        """Raise `NotAuthorizedError` unless the actor holds the scope."""
        ...

    def scopes_for(self, actor_role: str) -> frozenset[Scope]: ...


class AuditPort(Protocol):
    async def record(
        self,
        actor: Actor,
        action: str,
        *,
        target: str | None = None,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None: ...
