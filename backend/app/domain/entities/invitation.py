"""Invitation and recovery code entities.

The platform never transmits a credential. Account creation issues a
single-use, expiring token whose hash alone is stored; the administrator
delivers the link out of band and the recipient chooses their own password
and enrols TOTP in one flow. Password reset uses the same mechanism.
See docs/architecture/security.md section 5.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InvitationPurpose(StrEnum):
    ONBOARD = "onboard"
    PASSWORD_RESET = "password_reset"  # noqa: S105  (a purpose label, not a credential)


@dataclass(frozen=True, slots=True)
class Invitation:
    id: str
    user_id: str
    token_hash: str
    """Only the hash is stored. The plaintext token exists once, in the link
    handed to the administrator, and is never recoverable afterwards."""

    purpose: InvitationPurpose
    expires_at: datetime
    consumed_at: datetime | None = None

    def is_usable(self, now: datetime) -> bool:
        return self.consumed_at is None and self.expires_at > now


@dataclass(frozen=True, slots=True)
class RecoveryCode:
    id: str
    user_id: str
    code_hash: str
    used_at: datetime | None = None
