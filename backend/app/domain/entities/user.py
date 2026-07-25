"""Platform user.

Accounts are invitation only; there is no self-registration. A user who only
ever works over the tailnet needs no password, so both credential columns are
nullable. A user who needs the public entrance is issued a single-use
invitation link and sets their own password and TOTP; the platform never
transmits a credential. See docs/architecture/security.md sections 5.3, 5.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.actor import Role
from app.domain.entities.tenant import DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class User:
    id: str
    login: str
    display_name: str
    role: Role

    tenant_id: str = DEFAULT_TENANT_ID
    """Which tenant this account belongs to. Defaulted so the many constructions
    that predate multi-tenancy keep compiling; the identity layer and the
    invitation flow set it explicitly, and the tenant-scoped repositories stamp
    it on write. See docs/architecture/security.md section 7.3."""

    tailscale_login: str | None = None

    password_hash: str | None = None
    totp_secret: str | None = None
    """Encrypted at rest. Never returned after enrolment, never logged."""

    totp_last_counter: int | None = None
    """Highest accepted TOTP time counter. Codes at or below it are rejected,
    which is what stops a code observed in a phishing proxy from being reused
    inside its 30 second window."""

    created_at: datetime | None = None
    """Set by the repository on first write and read back afterwards.

    `None` means "not persisted yet", which is why it is not required at
    construction: the use case that creates a user should not have to invent a
    value the database is about to assign.
    """

    debug_logging_until: datetime | None = None
    disabled_at: datetime | None = None

    @property
    def can_use_public_entrance(self) -> bool:
        """Local credentials are only complete once TOTP is enrolled, so an
        account never exists in a password-only state."""
        return self.password_hash is not None and self.totp_secret is not None
