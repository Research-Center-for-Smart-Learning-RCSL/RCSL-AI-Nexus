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
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node, NodeStatus
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
    async def set_state(self, model_id: str, state: ModelState) -> None: ...
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
        self, since: datetime, until: datetime, unit: BucketUnit
    ) -> list[UsageBucket]:
        """Usage grouped by time bucket and capability, for the analytics charts.

        One query grouped by `(date_trunc(unit, at), capability)`; the use case
        folds the rows into per-bucket totals and per-capability series. Scoped,
        so a tenant's charts show only its own traffic.
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
