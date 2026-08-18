"""Persistence ports.

Grouped in one module because they share a shape and are always implemented
together by the same adapter package. The domain depends on these Protocols
only; nothing here knows about SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.entities.api_key import ApiKey
from app.domain.entities.audit import AuditEntry
from app.domain.entities.evaluation import EvaluationReport, EvaluationRun
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary
from app.domain.entities.prompt_template import PromptTemplate
from app.domain.entities.refusal import Refusal
from app.domain.entities.retention import RetentionDataset, RetentionPolicy
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord
from app.domain.entities.user import User


class TenantRepositoryPort(Protocol):
    """Platform-global, not tenant-scoped: tenants are the boundary, not data
    inside one."""

    async def get(self, tenant_id: str) -> Tenant | None: ...
    async def get_by_name(self, name: str) -> Tenant | None: ...
    async def list_all(self) -> list[Tenant]: ...
    async def save(self, tenant: Tenant) -> None: ...


class ModelRepositoryPort(Protocol):
    async def get(self, model_id: str) -> Model | None: ...
    async def get_by_alias(self, alias: str) -> Model | None: ...
    async def list_all(self) -> list[Model]: ...
    async def list_loaded(self, node_id: str) -> list[Model]: ...

    async def list_occupying_memory(self, node_id: str) -> list[Model]:
        """Loaded models plus those mid-load. A LOADING model already holds or
        is about to hold its memory, so the budget must count it or two
        concurrent loads each see room the other is taking."""
        ...

    async def save(self, model: Model) -> None: ...

    async def set_state(self, model_id: str, state: ModelState) -> None:
        """Write intent, and clear the observation that now predates it.

        The pairing is the contract, not an implementation detail. Readers rank
        observation over intent, so an observation taken before this transition
        would outrank the transition — a model loaded a second ago would keep
        routing as `downloaded` until the next sweep. Null means "not currently
        observed", which sends every reader back to intent until the heartbeat
        looks again."""
        ...

    async def set_observed(
        self, model_id: str, state: ModelState | None, memory_gb: float | None
    ) -> None:
        """Targeted observation write for the heartbeat, leaving intent alone.

        `state=None` records "not currently observable" and clears the
        timestamp with it: a stale observation must not keep the authority of
        a fresh one. Targeted for the same reason `set_status` on nodes is —
        both admin entrances run the sweep, and a read-modify-write here would
        let them overwrite each other's whole row."""
        ...

    async def delete(self, model_id: str) -> None: ...

    async def reconcile_transient_states(self, mapping: dict[ModelState, ModelState]) -> int:
        """Rewrite each transient state to a terminal one, returning the count.

        A `downloading`, `loading` or `unloading` row is a claim by a task, and
        a task does not survive a restart. Left alone the row is a permanent
        dead end: every lifecycle operation refuses a transient state, so
        nothing but hand-edited SQL can move it. This runs at deploy to clear
        the ones a crash stranded.
        """
        ...


class NodeRepositoryPort(Protocol):
    async def get(self, node_id: str) -> Node | None: ...
    async def list_all(self) -> list[Node]: ...
    async def save(self, node: Node) -> None: ...

    async def set_status(self, node_id: str, status: NodeStatus) -> None:
        """Targeted status write for the heartbeat.

        A full-row `save` would carry the whole entity back and could revert a
        concurrent edit to the name, memory or runtimes, the same read-modify-
        write hazard the key and user repositories already avoid. The heartbeat
        runs in both admin entrances, so this also has to be idempotent, which a
        single-column update is.
        """
        ...

    async def delete(self, node_id: str) -> None: ...


class RoutingPolicyRepositoryPort(Protocol):
    async def get(self, capability: str) -> RoutingPolicy | None: ...
    async def list_all(self) -> list[RoutingPolicy]: ...
    async def save(self, policy: RoutingPolicy) -> None: ...
    async def delete(self, capability: str) -> None: ...


class ApiKeyRepositoryPort(Protocol):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None: ...
    async def list_for_owner(self, owner_id: str) -> list[ApiKey]: ...
    async def list_all(self) -> list[ApiKey]: ...
    async def save(self, key: ApiKey) -> None: ...
    async def revoke(self, key_id: str, at: datetime) -> None: ...

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        """Update only the editable columns, refused if the key is revoked.

        A full-row save of a read-then-modified key writes `revoked_at` back
        from what it read, reviving a key a concurrent `revoke` had just
        killed. This touches named columns only, requires `revoked_at IS NULL`,
        and returns False if a revocation won the race.
        """
        ...

    async def delete_for_owner(self, owner_id: str) -> None:
        """Needed to delete a user: `api_keys.owner_id` is a foreign key, so
        the rows have to go with them. The use case decides whether deleting a
        user with live keys is allowed at all."""
        ...


class UserRepositoryPort(Protocol):
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_login(self, login: str) -> User | None: ...
    async def get_by_tailscale_login(self, login: str) -> User | None: ...
    async def list_all(self) -> list[User]: ...

    async def display_names(self) -> dict[str, str]:
        """User id to display name, and nothing else.

        The API-key listing needs to label each key's owner. Loading the full
        `User` entity for that pulls `password_hash` and `totp_secret` into a
        handler a `user`-role caller can reach, one edit away from leaking
        them; this reads only the two columns a label needs.
        """
        ...

    async def count(self) -> int:
        """Used by the bootstrap check: the first-admin setting is inert once
        any user exists."""
        ...

    async def save(self, user: User) -> None:
        """Full-row upsert; the entity must be complete or omitted columns are
        blanked. Prefer the targeted updates below where one exists."""
        ...

    async def insert_if_absent(self, user: User) -> User:
        """Insert, or return whichever row already holds this login.

        Exists for the first-admin bootstrap, where the guard is "no users
        yet" and a browser's first page load fires several requests at once.
        All of them see an empty table, all of them try to create the same
        account, and without an atomic claim the losers raise a constraint
        violation at commit. Returning the winner's row makes them agree
        instead.
        """
        ...

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        """Claim a TOTP counter, False if it is not newer than the stored one."""
        ...

    async def set_disabled(self, user_id: str, at: datetime | None) -> None: ...

    async def update_profile(self, user_id: str, *, display_name: str, role: str) -> None:
        """Update only display name and role, so a full-row save cannot revert
        a concurrent disable or TOTP-counter advance."""
        ...

    async def set_debug_logging_until(self, user_id: str, until: datetime | None) -> bool:
        """Open or close the account's debug window, False if it is disabled.

        Conditional on `disabled_at IS NULL` in the UPDATE rather than checked
        beforehand, for the reason `advance_totp_counter` gives: a read, a
        Python comparison and a write lets a concurrent disable land in
        between, and the window would then be open on an account somebody has
        just shut off.
        """
        ...

    async def delete(self, user_id: str) -> None: ...

    async def count_admins(self) -> int:
        """Guards the last administrator. Removing the only one leaves an
        instance nobody can manage, and the bootstrap setting does not come
        back: it is inert once any user row exists."""
        ...


class InvitationRepositoryPort(Protocol):
    async def get_by_token_hash(self, token_hash: str) -> Invitation | None: ...
    async def save(self, invitation: Invitation) -> None: ...

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        """False when another request claimed it first. Callers must check:
        the atomic guard is meaningless if its result is discarded."""
        ...

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None: ...

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None: ...
    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]: ...

    async def delete_recovery_codes(self, user_id: str) -> None:
        """Re-enrolling the second factor issues a fresh set.

        The old codes must go in the same transaction, or a set printed
        against a secret the user no longer holds stays redeemable, which is a
        standing bypass of the factor they just replaced.
        """
        ...

    async def delete_for_user(self, user_id: str) -> None:
        """Every invitation and recovery code belonging to a user.

        Both tables carry a foreign key to `users`, so deleting an account
        without this leaves the delete itself impossible. It also means an
        outstanding invitation cannot outlive the account it was issued for.
        """
        ...

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool: ...


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


class KnowledgeRepositoryPort(Protocol):
    """Collections and documents, tenant-scoped like the rest of the tenant's
    own data. The scoped adapter filters every read and stamps every write, so
    a use case here never names a tenant. See security.md section 7.3."""

    async def get_collection(self, collection_id: str) -> KnowledgeCollection | None: ...
    async def get_collection_by_name(self, name: str) -> KnowledgeCollection | None: ...
    async def list_collections(self) -> list[KnowledgeCollection]: ...
    async def save_collection(self, collection: KnowledgeCollection) -> None: ...

    async def delete_collection(self, collection_id: str) -> None:
        """Only ever called once the collection's documents are gone: the use
        case removes each document's stored bytes first, which the database
        cannot do for it, so a cascade here would orphan files on the volume."""
        ...

    async def get_document(self, document_id: str) -> KnowledgeDocument | None: ...

    async def list_documents(
        self, *, collection_id: str | None = None, limit: int, offset: int
    ) -> list[KnowledgeDocument]: ...

    async def count_documents(self, *, collection_id: str | None = None) -> int: ...

    async def save_document(self, document: KnowledgeDocument) -> None: ...

    async def set_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """A targeted status write, for the same reason `set_status` exists on
        nodes: the ingestion task read the row long before it writes, and a
        full-row save would carry a stale filename or collection back over a
        concurrent edit."""
        ...

    async def claim_document_status(
        self, document_id: str, expected: frozenset[DocumentStatus], claimed: DocumentStatus
    ) -> bool:
        """Take the row only if it is still in one of `expected`. True if taken.

        A conditional UPDATE, not a read followed by a write, and the difference
        is the whole point: two callers checking a status and then writing it
        both pass the check under READ COMMITTED, so both claim. That is the
        same hazard the TOTP counter avoids with `advance_totp_counter`, and it
        reaches the knowledge base through re-indexing, which unlike an upload
        can be requested twice for a document that already exists."""
        ...

    async def delete_document(self, document_id: str) -> None: ...

    async def reconcile_transient_documents(self, error: str) -> int:
        """Move every `extracting` or `indexing` row to `error`, returning the
        count. The ingestion task does not survive a restart, and every
        operation refuses a transient state, so without this a crash mid-ingest
        leaves a row nothing can move. The model registry has the same
        backstop for the same reason."""
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


class RecordPurgePort(Protocol):
    """Counting and deleting rows older than a cutoff, for retention.

    One protocol implemented by both the audit and usage repositories, so the
    retention use case holds a mapping of dataset to port and gains no `if` per
    table. Adding a third dataset is then a repository that satisfies this and
    an entry in that mapping.

    `count_older_than` exists so the screen can say what a purge would remove
    before it removes it. It is deliberately a separate call rather than a dry
    run: a dry run that shares a code path with the real thing is one edit away
    from deleting during a preview.

    **Unscoped by tenant, unlike every other repository here.** Retention is a
    platform-wide policy held by an administrator who is not confined to a
    tenant, and a purge that silently spared other tenants' rows would report a
    number that did not match what it did. The scope check is in the use case,
    where `retention:write` is admin-only.
    """

    async def count_older_than(self, cutoff: datetime) -> int: ...

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Returns the number of rows removed."""
        ...


class RetentionPolicyRepositoryPort(Protocol):
    async def list_policies(self) -> list[RetentionPolicy]:
        """Every dataset, including those never configured.

        The default is filled in by the caller rather than stored at migration
        time, so a dataset added later needs no backfill and the number in the
        code is the number in the absence of a decision.
        """
        ...

    async def get_policy(self, dataset: RetentionDataset) -> RetentionPolicy | None: ...

    async def set_policy(self, policy: RetentionPolicy) -> None:
        """Upsert. The row appears the first time somebody disagrees with the
        default, which is also the first time there is an author to record."""
        ...


class PromptTemplateRepositoryPort(Protocol):
    """Tenant-scoped, like the knowledge repository: the filter is the adapter's
    and comes from the tenant it was constructed with, never from a caller."""

    async def get(self, template_id: str) -> PromptTemplate | None: ...

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        """How a chat request resolves `"prompt_template": "code-review"`.

        Scoped, so the name a caller writes can only ever name their own
        tenant's template — which is what makes selection a choice among
        trusted values rather than a way to reach somebody else's text.
        """
        ...

    async def list_all(self) -> list[PromptTemplate]: ...

    async def save(self, template: PromptTemplate) -> None: ...

    async def delete(self, template_id: str) -> None: ...


class EvaluationRepositoryPort(Protocol):
    """Stored capability evaluations.

    Platform-global, like models and nodes: an evaluation describes the fleet
    rather than anyone's content, so there is no tenant to scope by.

    Reads return a whole `EvaluationReport` rather than the three tables it is
    assembled from. The task verdicts are a property of the set of models in a
    run, so a caller holding two of the three lists could compute one that is
    quietly wrong -- assembling in the adapter, once, is what stops that being
    possible at all.
    """

    async def list_runs(self) -> list[EvaluationRun]:
        """Every run, newest first. Carries no scores: the index is a list of
        what has been measured, and a page of it should not read three tables
        for figures nobody has asked for yet."""
        ...

    async def get_report(self, run_id: str) -> EvaluationReport | None: ...

    async def latest_report(self) -> EvaluationReport | None:
        """The most recent run by `ran_at`, which is what the screen opens on.

        By when it ran rather than when it was imported: a run loaded late is
        still an older reading, and ordering by import would let a backfill
        present itself as the current state of the fleet.
        """
        ...

    async def save_report(self, report: EvaluationReport) -> None:
        """Store a run, replacing any run carrying the same label.

        Replacement rather than a second row, because a corrected re-import is
        the expected case: the published 2026-08-15 figures are themselves a
        correction of that day's first reading.
        """
        ...

    async def delete_run(self, run_id: str) -> bool:
        """True when a run was deleted, False when there was none to delete."""
        ...
