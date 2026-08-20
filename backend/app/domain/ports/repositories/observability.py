"""Persistence observability boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.entities.audit import AuditEntry
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary
from app.domain.entities.refusal import Refusal
from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord


class PromptLogWriterPort(Protocol):
    """Append a §9.2 transcript.

    **Separate from the read port, and the reason is the transaction rather
    than the privilege split.** These were one Protocol for half a day, on the
    argument that splitting them would only restate a boundary `db_roles.py`
    already enforces — the gateway holds `INSERT` here and has its `SELECT`
    revoked, so a gateway calling a read would be refused by Postgres rather
    than by a type. That argument was fine and it was not the operative one.

    The operative one is that the two need **different transaction lifetimes**.
    A read belongs to the request that asked for it. A write must survive the
    request *failing*, because a debug window is opened precisely when a caller
    reports an error: staging the transcript on the request's own session meant
    that the exception which produced that error rolled the session back and
    took the transcript with it. Every successful request recorded fine and the
    one conversation somebody was looking for was the one that was never
    written. `PostgresAudit` already had its own session for exactly this
    reason, and this port did not.

    So the writer is handed a session factory, not a session — which is a
    difference the type system can hold, and the reason this is two Protocols.
    """

    async def record(self, entry: PromptLogEntry) -> None: ...


class PromptLogRepositoryPort(Protocol):
    """Read the §9.2 transcripts. See `PromptLogWriterPort` for why the write
    is not here."""

    async def get(self, entry_id: str) -> PromptLogEntry | None:
        """The full transcript, by id. The only method that returns content."""
        ...

    async def list_summaries(
        self,
        *,
        actor_id: str | None,
        api_key_id: str | None,
        capability: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[PromptLogSummary]:
        """A page of the table, carrying no message content.

        Deliberately not `list_entries` returning full rows that a caller then
        strips. The point is that the text is never selected: a page of fifty
        transcripts is a few hundred megabytes of the most sensitive data in the
        schema, and the safest place for it is the column it is already in.
        """
        ...

    async def count_entries(
        self,
        *,
        actor_id: str | None,
        api_key_id: str | None,
        capability: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int: ...


class RefusalWriterPort(Protocol):
    """Append a refusal.

    Split from the read port for the same reason `PromptLogWriterPort` is, and
    the reason binds harder here: this write happens *while the request is
    failing*. Every row in this table is written from an exception handler, so
    a writer staged on the request's own session would be rolled back by the
    very exception it exists to record — the failure mode that cost a day of
    transcripts on 2026-08-08, reproduced on a table where it would be the only
    outcome rather than an occasional one.

    Best-effort by contract. A refusal that cannot be stored must still be
    returned to the caller as the refusal it is, so implementations swallow and
    log their own failures rather than raising into a handler that is already
    rendering an error.
    """

    async def record(self, refusal: Refusal) -> None: ...


class RefusalRepositoryPort(Protocol):
    """Read refusals. See `RefusalWriterPort` for why the write is not here."""

    async def list_refusals(
        self,
        *,
        actor_id: str | None,
        actor_display: str | None,
        api_key_id: str | None,
        code: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[Refusal]:
        """A page, newest first.

        No summary type, unlike `prompt_logs`. There the list and the row are
        two reads because the row is a conversation; here the row *is* the
        summary — a code, a status, a message the caller already read and the
        figures that came with it — so a second request to open one would
        disclose nothing the page had not.

        `actor_display` is the one filter here that is not an equality. It
        matches a substring, case-insensitively, because it is what the reader
        can actually see: the account id is a uuid and a screen that can only
        filter by one is a screen you cannot search. It is also the only way to
        find the refusals of an account that has since been deleted, whose name
        survives on this row and nowhere else, and the only way to find one
        gateway key's by the handle it is known by.
        """
        ...

    async def count_refusals(
        self,
        *,
        actor_id: str | None,
        actor_display: str | None,
        api_key_id: str | None,
        code: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int: ...


class UsageRepositoryPort(Protocol):
    async def record(self, usage: UsageRecord) -> None: ...
    async def tokens_used_today(self, api_key_id: str) -> int: ...

    async def last_used_by_key(self) -> dict[str, datetime]:
        """When each key was last seen, derived rather than stored.

        A `last_used_at` column on `api_keys` would mean the gateway writing to
        that table on every request, which §6 of the security document says it
        must not be able to do: the point of the account split is that a
        compromised gateway cannot touch credentials. The usage table already
        records the same fact, is written by the account that should write it,
        and is indexed on `(api_key_id, at)`.

        One aggregate for every key rather than one query per key, because the
        caller is rendering a list.
        """
        ...

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        """`(requests, tokens)` across all callers, for the dashboard."""
        ...

    async def bucketed_usage(
        self,
        since: datetime,
        until: datetime,
        unit: BucketUnit,
        *,
        actor_id: str | None = None,
    ) -> list[UsageBucket]:
        """Usage grouped by time bucket and capability, for the analytics charts.

        One query grouped by `(date_trunc(unit, at), capability)`; the use case
        folds the rows into per-bucket totals and per-capability series. Scoped,
        so a tenant's charts show only its own traffic.

        `actor_id` narrows further, to the usage attributed to one account, which
        is what `usage:read_own` grants sight of. It filters on `actor_id` rather
        than `api_key_id` because the gateway resolves an API key to its
        **owner** (`api_key_auth.py` builds the actor with `id=key.owner_id`), so
        one account's usage is every row its keys produced plus anything it ran
        through the admin chat, and no join is needed to say so. Keyword-only:
        the difference between the tenant's figures and one person's is not
        something to express as a third positional argument.
        """
        ...


class AuditLogRepositoryPort(Protocol):
    """Read side of the audit log. The write side is `AuditPort`, whose adapter
    commits in its own transaction; this is an ordinary tenant-scoped query."""

    async def list_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[AuditEntry]: ...

    async def count_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int:
        """Total matching the same filters, for the pager."""
        ...
