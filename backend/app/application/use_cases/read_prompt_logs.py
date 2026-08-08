"""Read the §9.2 transcripts: which conversations were captured, and one of them.

**Two operations, and the split between them is the whole design.** Listing
answers "what is in here" and discloses no message content; reading a
transcript answers "what did they type" and discloses all of it. They are
separate methods against separate repository reads, they return different
types, and **only the second writes an audit row**.

The reason is that an audit event has to name something a reader can act on.
`prompt_log.list` fires whenever the screen refreshes and would tell an
investigator that somebody opened a page — an event so frequent it is noise,
and one that describes no disclosure. `prompt_log.read` fires once per
conversation actually looked at, names that conversation's id, and is therefore
the row that answers the question this control exists to make answerable: the
window recorded what somebody typed, so *who then read it*.

That question had no answer before 2026-08-08. Opening a debug window has been
audited since the switch shipped (`api_key.debug_window_set`,
`user.debug_window_set`), which records who widened what the platform reveals —
but nothing recorded who then consumed it, because until now nothing was
revealed. Adding the disclosure without adding its record would have left the
same half-covered shape §12's sweep found on the identity plane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary
from app.domain.exceptions import PromptLogNotFoundError
from app.domain.ports.repositories import PromptLogRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
"""Bounded for the reason `ReadAuditLog` is bounded, and one more. An operator
UI never needs the whole table at once and an unbounded limit is a memory lever
on an append-only table — and here the rows are the widest in the schema, so
the lever is longer."""


@dataclass(frozen=True, slots=True)
class PromptLogPage:
    entries: list[PromptLogSummary]
    total: int
    limit: int
    offset: int


class ReadPromptLogs:
    def __init__(
        self,
        transcripts: PromptLogRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._transcripts = transcripts
        self._authz = authz
        self._audit = audit

    async def list_page(
        self,
        actor: Actor,
        *,
        actor_id: str | None = None,
        api_key_id: str | None = None,
        capability: str | None = None,
        request_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> PromptLogPage:
        """Metadata only. No audit row — see the module docstring."""
        self._authz.require(actor, Scope.PROMPT_LOG_READ)

        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)

        entries = await self._transcripts.list_summaries(
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            request_id=request_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total = await self._transcripts.count_entries(
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            request_id=request_id,
            since=since,
            until=until,
        )
        return PromptLogPage(entries=entries, total=total, limit=limit, offset=offset)

    async def read_transcript(self, actor: Actor, entry_id: str) -> PromptLogEntry:
        """One conversation, in full, and the audit row that says who read it.

        The record is written **after** the read succeeds and only then. A row
        for an id that resolved to nothing would claim a disclosure that did not
        happen, and this is a table where a false positive costs an
        investigator the same as a false negative.

        A miss is `NotFoundError` rather than a refusal, and the repository is
        tenant-scoped, so an id belonging to another tenant is indistinguishable
        from an id that never existed. Answering "forbidden" there would confirm
        the row exists, which is a cross-tenant read of one bit.
        """
        self._authz.require(actor, Scope.PROMPT_LOG_READ)

        entry = await self._transcripts.get(entry_id)
        if entry is None:
            raise PromptLogNotFoundError(detail=f"no transcript {entry_id}")

        await self._audit.record(
            actor=actor,
            action="prompt_log.read",
            target=entry_id,
            outcome="success",
            # Handles only. Nothing from `messages`, `completion` or `reasoning`
            # goes in here — the audit log has its own, far longer retention
            # (360 days against 7), so a snippet copied into `detail` would
            # outlive by a year the very record the retention ceiling exists to
            # expire. That is the one way this feature could quietly undo its
            # own bound, so it is stated where the temptation is.
            detail={
                "capability": entry.capability,
                "model_alias": entry.model_alias,
                "subject_actor_id": entry.actor_id,
                "at": entry.at.isoformat(),
            },
        )
        return entry
