"""Read refusals: your own always, anyone's with a scope.

**The two reads are one method with one difference, deliberately.** Listing
your own and listing everyone's return the same rows in the same shape, because
a refusal is the same object whoever is looking at it — there is no summary and
no second request to open one, since the row *is* what the caller was told.
What differs is the filter and whether an audit entry is written.

**Only the cross-account read is audited.** `refusal.read_any` fires when
somebody looks at refusals that are not their own; reading your own is the
feature working as designed, and a row per screen refresh would be the noise
`prompt_log.list` was denied for the same reason. What the audit row records is
a reader reaching across accounts, because a month of somebody's 413s describes
how they work even though it holds nothing they typed.

**The narrowing is done here and not trusted to the caller.** A request without
`refusal:read_all` has `actor_id` overwritten with the reader's own, whatever it
asked for — not refused, overwritten, so that the screen's own filters keep
working for a person who may only see themselves. An earlier arrangement that
refused instead would have made "clear the filter" a 403 on the page every user
is expected to open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.refusal import Refusal
from app.domain.ports.repositories import RefusalRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
"""Bounded for the reason every other paged read here is: an operator UI never
needs the whole table at once, and an unbounded limit is a memory lever on an
append-only table that anyone with a key can add rows to."""


@dataclass(frozen=True, slots=True)
class RefusalPage:
    entries: list[Refusal]
    total: int
    limit: int
    offset: int
    scoped_to_self: bool
    """Whether the reader was narrowed to their own refusals.

    On the response so the screen can say so, rather than showing an empty
    filter box that silently does nothing. A page that quietly returns a subset
    of what its controls imply is the shape a reader mistakes for "there is
    nothing there".
    """


class ReadRefusals:
    def __init__(
        self,
        refusals: RefusalRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._refusals = refusals
        self._authz = authz
        self._audit = audit

    async def list_page(
        self,
        actor: Actor,
        *,
        actor_id: str | None = None,
        api_key_id: str | None = None,
        code: str | None = None,
        request_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> RefusalPage:
        self._authz.require(actor, Scope.REFUSAL_READ_OWN)

        may_read_any = actor.has(Scope.REFUSAL_READ_ALL)
        if not may_read_any:
            actor_id = actor.id
            # The key filter is left alone: a caller narrowing to one of their
            # own keys is the ordinary use, and the actor filter above already
            # confines the result to rows that are theirs.

        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)

        entries = await self._refusals.list_refusals(
            actor_id=actor_id,
            api_key_id=api_key_id,
            code=code,
            request_id=request_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total = await self._refusals.count_refusals(
            actor_id=actor_id,
            api_key_id=api_key_id,
            code=code,
            request_id=request_id,
            since=since,
            until=until,
        )

        if may_read_any and actor_id != actor.id:
            # Once per request, naming what was reached for rather than the
            # rows returned: an audit row per refusal read would grow with the
            # page size and describe the same act several times.
            await self._audit.record(
                actor,
                AuditAction.REFUSAL_READ_ANY,
                target=actor_id or "all",
                detail={"code": code or "", "returned": str(len(entries))},
            )

        return RefusalPage(
            entries=entries,
            total=total,
            limit=limit,
            offset=offset,
            scoped_to_self=not may_read_any,
        )
