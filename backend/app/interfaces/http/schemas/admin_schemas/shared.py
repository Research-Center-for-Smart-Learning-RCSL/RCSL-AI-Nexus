"""Admin shared schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator

from app.adapters.authz.role_authorization import ASSIGNABLE_ROLES
from app.domain.entities.actor import Role


def _as_utc(value: datetime) -> datetime:
    """Read a naive value as UTC rather than rejecting it.

    The expiry field is rendered as `<input type="date">`, which can only
    produce `YYYY-MM-DD`. Pydantic parses that into a **naive** datetime, and
    comparing one to `datetime.now(UTC)` raises `TypeError` — not a
    `DomainError`, so it escaped the handler as a bare 500 and no API key
    could ever be issued from the UI.

    Coercing rather than rejecting, because a date with no zone is what the
    form is able to send and "midnight UTC on that day" is what it means.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _human_role(role: Role) -> Role:
    """Refuses the SERVICE role on a human account.

    `SERVICE` exists for API keys. `ASSIGNABLE_ROLES` is the list a person may
    hold, and it is every role except that one — accepting it here would create
    an account whose permissions were designed for a machine credential.

    The message enumerates from that list rather than naming roles inline. It
    said "role must be 'admin' or 'user'" for a day after there were six, which
    is a 422 that tells the caller two of the answers it could have given.
    """
    if role is Role.SERVICE:
        allowed = ", ".join(repr(r.value) for r in ASSIGNABLE_ROLES)
        raise ValueError(f"role must be one of {allowed}")
    return role


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
HumanRole = Annotated[Role, AfterValidator(_human_role)]
