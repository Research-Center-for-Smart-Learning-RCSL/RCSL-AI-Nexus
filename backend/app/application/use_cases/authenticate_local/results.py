"""Authentication step results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PasswordResult:
    user_id: str
    """Held by the caller between the two login steps. Carries no privilege
    on its own: a session is only issued after the TOTP step succeeds."""
