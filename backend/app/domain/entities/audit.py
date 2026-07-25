"""A recorded action, on the read side.

The write side is `AuditPort` / `PostgresAudit`, which commits each row in its
own transaction so a failed request still leaves its trail. This entity is the
read side: a normal tenant-scoped query over the same append-only table, for the
logs view. Kept separate from the write path because reading is an ordinary
request-session query and must not borrow the writer's independent-transaction
machinery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.tenant import DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: str
    actor_id: str
    actor_display: str
    """Login or key handle, never a secret; safe to render."""

    actor_source: str
    action: str
    target: str | None
    outcome: str
    detail: dict[str, str]
    """Identifiers and reasons only. Section 12 forbids a credential, token,
    prompt, or completion here, so the read path can surface it verbatim."""

    at: datetime
    tenant_id: str = DEFAULT_TENANT_ID
