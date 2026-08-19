"""API-key create, update, revoke, and debug-window commands."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.entities.audit import AuditAction
from app.domain.entities.capability import ISSUABLE_CAPABILITIES
from app.domain.exceptions import (
    ApiKeyStateConflictError,
    UserNotFoundError,
)
from app.domain.services.debug_window import debug_window_until

from .authorization import ApiKeyPolicyMixin
from .policy import UNCHANGED, IssuedApiKey, Unchanged, _parse_cidrs


class ApiKeyCommandsMixin(ApiKeyPolicyMixin):
    async def list_visible(self, actor: Actor) -> tuple[list[ApiKey], dict[str, datetime]]:
        """Returns the keys and, separately, when each was last used.

        Last use is derived from `usage_records` rather than stored on the key,
        because maintaining a column would mean the gateway writing to
        `api_keys` on every request. See security.md section 6.
        """
        self._authz.require(actor, Scope.API_KEY_READ_OWN)

        if actor.has(Scope.API_KEY_WRITE_ANY):
            keys = await self._keys.list_all()
        else:
            keys = await self._keys.list_for_owner(actor.id)

        return keys, await self._usage.last_used_by_key()

    async def create(
        self,
        actor: Actor,
        *,
        name: str,
        owner_id: str,
        scopes: Sequence[str],
        expires_at: datetime,
        rate_limit_rpm: int,
        quota_tokens_per_day: int | None,
        allowed_cidrs: Sequence[str],
        default_capability: str | None = None,
    ) -> IssuedApiKey:
        self._require_owner_permission(actor, owner_id)

        if await self._users.get(owner_id) is None:
            # The column is a foreign key, so this would fail at commit
            # anyway. Caught here so the answer is 404 with a reason rather
            # than a 500 from the database.
            raise UserNotFoundError(detail=f"no owner {owner_id}")

        self._assert_expiry_sane(expires_at)

        unknown = sorted(set(scopes) - ISSUABLE_CAPABILITIES)
        if unknown:
            raise ApiKeyStateConflictError(detail=f"unknown capabilities {unknown}")

        # After the check above, so a default naming something that is not a
        # capability at all is answered by the message about capabilities.
        self._assert_default_capability(default_capability, scopes)

        issued = self._service.issue()
        key = ApiKey(
            id=str(uuid.uuid4()),
            key_id=issued.key_id,
            digest=issued.digest,
            name=name.strip(),
            owner_id=owner_id,
            expires_at=expires_at,
            scopes=frozenset(scopes),
            allowed_cidrs=_parse_cidrs(allowed_cidrs),
            rate_limit_rpm=rate_limit_rpm,
            quota_tokens_per_day=quota_tokens_per_day,
            default_capability=default_capability,
        )
        await self._keys.save(key)

        # Read back, because `created_at` is assigned by the database and the
        # in-memory entity carries None for it. The response model allows
        # None, but the frontend's schema does not, so returning the unsaved
        # entity made the parse throw *after* the key existed — destroying the
        # plaintext, which has no second copy anywhere.
        stored = await self._keys.get_by_key_id(key.key_id) or key

        await self._audit.record(
            actor,
            AuditAction.API_KEY_ISSUED,
            target=key.key_id,
            detail={
                "name": key.name,
                "owner": owner_id,
                # Recorded from the start rather than only on edit: a key
                # issued with a default behaves differently from one without,
                # and the audit log is where that is read back.
                "default_capability": default_capability or "",
            },
        )
        return IssuedApiKey(key=stored, plaintext=issued.plaintext)

    async def update(
        self,
        actor: Actor,
        key_id: str,
        *,
        name: str | None = None,
        scopes: Sequence[str] | None = None,
        expires_at: datetime | None = None,
        rate_limit_rpm: int | None = None,
        quota_tokens_per_day: int | None = None,
        allowed_cidrs: Sequence[str] | None = None,
        default_capability: str | None | Unchanged = UNCHANGED,
    ) -> ApiKey:
        key = await self._require(key_id)
        self._require_owner_permission(actor, key.owner_id)

        if key.revoked_at is not None:
            # Editing a revoked key would produce something that looks active
            # in a list and is not. Reissue instead.
            raise ApiKeyStateConflictError(detail=f"key {key_id} is revoked")

        if expires_at is not None:
            self._assert_expiry_sane(expires_at)

        if scopes is not None:
            unknown = sorted(set(scopes) - ISSUABLE_CAPABILITIES)
            if unknown:
                raise ApiKeyStateConflictError(detail=f"unknown capabilities {unknown}")

        resulting_scopes = frozenset(scopes) if scopes is not None else key.scopes
        resulting_default = (
            key.default_capability
            if isinstance(default_capability, Unchanged)
            else default_capability
        )
        # Against the scopes this edit *results in*, not the ones it started
        # with. Narrowing a key's capabilities out from under a default it
        # already had is refused rather than quietly clearing it: the two edits
        # are one request, and dropping half of it is how a setting comes to
        # differ from what the operator was last shown.
        self._assert_default_capability(resulting_default, resulting_scopes)

        updated = replace(
            key,
            name=name.strip() if name is not None else key.name,
            scopes=frozenset(scopes) if scopes is not None else key.scopes,
            expires_at=expires_at if expires_at is not None else key.expires_at,
            rate_limit_rpm=(rate_limit_rpm if rate_limit_rpm is not None else key.rate_limit_rpm),
            quota_tokens_per_day=(
                quota_tokens_per_day
                if quota_tokens_per_day is not None
                else key.quota_tokens_per_day
            ),
            allowed_cidrs=(
                _parse_cidrs(allowed_cidrs) if allowed_cidrs is not None else key.allowed_cidrs
            ),
            default_capability=resulting_default,
        )
        # A targeted update of the editable columns only, guarded on
        # `revoked_at IS NULL`. The revoked check above is a courtesy that
        # gives a clear error; this is what actually prevents an edit racing a
        # concurrent revoke from reviving the key, and it refuses if the
        # revoke won.
        if not await self._keys.update_settings(
            key.key_id,
            {
                "name": updated.name,
                "scopes": sorted(updated.scopes),
                "expires_at": updated.expires_at,
                "rate_limit_rpm": updated.rate_limit_rpm,
                "quota_tokens_per_day": updated.quota_tokens_per_day,
                "allowed_cidrs": [str(n) for n in updated.allowed_cidrs],
                "default_capability": updated.default_capability,
            },
        ):
            raise ApiKeyStateConflictError(detail=f"key {key_id} was revoked concurrently")

        # Scope changes are audited by name, because they are the edit that
        # changes what a leaked key can reach.
        await self._audit.record(
            actor,
            AuditAction.API_KEY_UPDATED,
            target=key.key_id,
            detail={
                "scopes": ",".join(sorted(updated.scopes)),
                "default_capability": updated.default_capability or "",
            },
        )
        return updated

    async def revoke(self, actor: Actor, key_id: str) -> None:
        key = await self._require(key_id)
        self._require_owner_permission(actor, key.owner_id)

        await self._keys.revoke(key_id, self._clock.now())
        await self._audit.record(actor, AuditAction.API_KEY_REVOKED, target=key_id)

    async def set_debug_window(self, actor: Actor, key_id: str, *, minutes: int) -> ApiKey:
        """Open, extend, or close (minutes=0) the key's debug window.

        While the window is open, error responses to this key carry
        `error.detail` — the operator-facing string that is otherwise
        log-only. Audited for the same reason it is bounded: it changes what
        the platform reveals, and the record of who opened it belongs next to
        the record of what was revealed.

        The ceiling is in `domain/services/debug_window.py`, shared with the
        user-side window rather than restated here.
        """
        until = debug_window_until(self._clock.now(), minutes)
        key = await self._require(key_id)
        self._require_owner_permission(actor, key.owner_id)
        if key.revoked_at is not None:
            raise ApiKeyStateConflictError(detail=f"key {key_id} is revoked")

        if not await self._keys.update_settings(key.key_id, {"debug_logging_until": until}):
            raise ApiKeyStateConflictError(detail=f"key {key_id} was revoked concurrently")

        await self._audit.record(
            actor,
            AuditAction.API_KEY_DEBUG_WINDOW_SET,
            target=key.key_id,
            detail={"until": until.isoformat() if until else "off"},
        )
        return replace(key, debug_logging_until=until)
