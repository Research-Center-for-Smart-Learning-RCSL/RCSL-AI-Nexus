"""Read the audit log, for the logs view.

The write path records every administrative action already; this exposes it,
filtered and paged, to an administrator holding `logs:read`. Tenant scoping is
enforced by the repository the di builder constructs, so this use case cannot
read another tenant's trail even by asking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditEntry
from app.domain.ports.repositories import AuditLogRepositoryPort
from app.domain.ports.security_ports import AuthorizationPort

# The page cannot be unbounded: an operator UI never needs the whole table at
# once, and an unbounded limit is a memory lever on an append-only table.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    entries: list[AuditEntry]
    total: int
    limit: int
    offset: int


class ReadAuditLog:
    def __init__(self, entries: AuditLogRepositoryPort, authz: AuthorizationPort) -> None:
        self._entries = entries
        self._authz = authz

    async def execute(
        self,
        actor: Actor,
        *,
        action: str | None = None,
        outcome: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> AuditLogPage:
        self._authz.require(actor, Scope.LOGS_READ)

        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)

        entries = await self._entries.list_entries(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total = await self._entries.count_entries(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        return AuditLogPage(entries=entries, total=total, limit=limit, offset=offset)
