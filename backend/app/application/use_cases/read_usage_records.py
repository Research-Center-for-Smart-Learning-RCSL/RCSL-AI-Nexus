"""One page of individual requests, which nothing could show until 2026-09-07.

`usage_records` has been written since the first migration and every reader of
it was an aggregate: totals for the dashboard, buckets for the charts, a sum for
the quota. So the platform recorded what each request did — its model, its size,
its latency, whether it finished — and could not show anybody a single one of
them. "Which request was the 413 the integrator is quoting?" was answerable only
from a log line that rotates.

Compaction is what made that gap worth closing rather than merely noting.
`c1d5f8a3e497` added three columns saying what a prompt was reduced to, on the
argument that a header the client may not read needs durable evidence behind it
— and then the evidence was as unreadable as the header. §3 of
automatic-context-compaction.md asks for the disclosure to be visible beside the
request, and this is the surface that sentence assumed already existed.

**The narrowing is done here rather than at the route**, exactly as
`read_refusals.py` does it: a reader without `usage:read_all` has `actor_id`
overwritten with their own, whatever they asked for. Not refused — overwritten —
so the screen's filters keep working for a person who may only see themselves,
and clearing a filter is not a 403 on a page every account can open.

**The cross-account read is audited and the aggregate charts are not.** The
charts are counts per hour per capability and describe a tenant. This is one row
per request with a timestamp, and a month of it describes how a person works.
That is the same line `refusal.read_any` draws.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.usage import UsageRecord
from app.domain.ports.repositories import UsageRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
"""The same bound as every other paged read here, for the same reason: an
operator UI never needs the whole table, and this one is append-only and
writable by anyone holding a key."""


@dataclass(frozen=True, slots=True)
class UsageRecordPage:
    entries: list[UsageRecord]
    total: int
    limit: int
    offset: int
    scoped_to_self: bool
    """Whether the reader was narrowed to their own requests, so the screen can
    say so rather than showing a filter box that silently does nothing."""


class ReadUsageRecords:
    def __init__(
        self,
        usage: UsageRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._usage = usage
        self._authz = authz
        self._audit = audit

    async def list_page(
        self,
        actor: Actor,
        *,
        actor_id: str | None = None,
        api_key_id: str | None = None,
        capability: str | None = None,
        compacted: bool | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> UsageRecordPage:
        self._authz.require(actor, Scope.USAGE_READ_OWN)

        may_read_any = actor.has(Scope.USAGE_READ_ALL)
        if not may_read_any:
            actor_id = actor.id
            # The key filter is deliberately left alone: narrowing to one of
            # your own keys is the ordinary use, and the actor filter above
            # already confines the result to rows that are yours.

        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)

        # Spelled out at both call sites rather than packed into a dict and
        # splatted. A `**filters` dict collapses to its join type — here
        # `str | bool | datetime | None` — so every argument type-checks against
        # every parameter, and the check that `compacted` reaches the boolean
        # rather than the capability stops happening.
        entries = await self._usage.list_records(
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            compacted=compacted,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total = await self._usage.count_records(
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            compacted=compacted,
            since=since,
            until=until,
        )

        if may_read_any and actor_id != actor.id:
            # Once per request, naming what was reached for rather than the rows
            # returned: a row per record would grow with the page size and
            # describe the same act several times.
            await self._audit.record(
                actor,
                AuditAction.USAGE_READ_ANY,
                target=actor_id or "all",
                detail={"api_key_id": api_key_id or "", "capability": capability or ""},
            )

        return UsageRecordPage(
            entries=entries,
            total=total,
            limit=limit,
            offset=offset,
            scoped_to_self=not may_read_any,
        )
