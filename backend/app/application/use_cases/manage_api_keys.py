"""Issuing, editing and revoking API keys.

The plaintext exists in exactly one place: the response that issued it. Only
an HMAC digest is stored, so an administrator who closes the dialog reissues
rather than looks it up, and a database read yields nothing usable.

Two rules here are not obvious from the entity.

**Expiry is mandatory and must be in the future.** The column is NOT NULL, but
a caller could still supply a date already past, producing a key that is dead
on arrival and reads as a platform fault. Rotation is the point of the field,
so it is checked rather than assumed.

**Scope is narrowed at verification, not widened here.** Whatever list is
stored, `adapters/authz` maps a service actor onto a fixed set, so no edit to
this table can promote a key into the control plane.

See docs/architecture/security.md section 4.2.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from ipaddress import IPv4Network, IPv6Network, ip_network

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.entities.capability import KNOWN_CAPABILITIES
from app.domain.exceptions import (
    InvalidCidrError,
    ModelStateConflictError,
    NotAuthorizedError,
    UserNotFoundError,
)
from app.domain.ports.repositories import (
    ApiKeyRepositoryPort,
    UsageRepositoryPort,
    UserRepositoryPort,
)
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.domain.services.api_key_service import ApiKeyService
from app.shared.clock import Clock

"""Checked at issue so a typo becomes an error rather than a key that is
silently powerless. The authoritative narrowing still happens at verification;
this is about giving the operator an answer.

Imported from the domain rather than defined here: routing policies and the
gateway's scope mapping need the same set, and the two that kept their own copy
had each drifted from it. See `domain/entities/capability.py`."""


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    key: ApiKey
    plaintext: str
    """The only copy that will ever exist."""


class ManageApiKeys:
    def __init__(
        self,
        keys: ApiKeyRepositoryPort,
        users: UserRepositoryPort,
        usage: UsageRepositoryPort,
        service: ApiKeyService,
        authz: AuthorizationPort,
        audit: AuditPort,
        clock: Clock,
        *,
        max_lifetime_days: int = 365,
    ) -> None:
        self._keys = keys
        self._users = users
        self._usage = usage
        self._service = service
        self._authz = authz
        self._audit = audit
        self._clock = clock
        self._max_lifetime = timedelta(days=max_lifetime_days)

    def _assert_expiry_sane(self, expires_at: datetime) -> None:
        """Bounded at both ends.

        A date already past produces a key that is dead on arrival and reads
        as a platform fault. A date far enough ahead defeats the field's only
        purpose: expiry is here to force rotation, and `9999-12-31` satisfied
        "in the future" while rotating nothing.
        """
        now = self._clock.now()
        if expires_at <= now:
            raise ModelStateConflictError(detail=f"expiry {expires_at} is not in the future")
        if expires_at > now + self._max_lifetime:
            raise ModelStateConflictError(
                detail=f"expiry {expires_at} is beyond the {self._max_lifetime.days} day maximum"
            )

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
    ) -> IssuedApiKey:
        self._require_owner_permission(actor, owner_id)

        if await self._users.get(owner_id) is None:
            # The column is a foreign key, so this would fail at commit
            # anyway. Caught here so the answer is 404 with a reason rather
            # than a 500 from the database.
            raise UserNotFoundError(detail=f"no owner {owner_id}")

        self._assert_expiry_sane(expires_at)

        unknown = sorted(set(scopes) - KNOWN_CAPABILITIES)
        if unknown:
            raise ModelStateConflictError(detail=f"unknown capabilities {unknown}")

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
            "api_key.issued",
            target=key.key_id,
            detail={"name": key.name, "owner": owner_id},
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
    ) -> ApiKey:
        key = await self._require(key_id)
        self._require_owner_permission(actor, key.owner_id)

        if key.revoked_at is not None:
            # Editing a revoked key would produce something that looks active
            # in a list and is not. Reissue instead.
            raise ModelStateConflictError(detail=f"key {key_id} is revoked")

        if expires_at is not None:
            self._assert_expiry_sane(expires_at)

        if scopes is not None:
            unknown = sorted(set(scopes) - KNOWN_CAPABILITIES)
            if unknown:
                raise ModelStateConflictError(detail=f"unknown capabilities {unknown}")

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
            },
        ):
            raise ModelStateConflictError(detail=f"key {key_id} was revoked concurrently")

        # Scope changes are audited by name, because they are the edit that
        # changes what a leaked key can reach.
        await self._audit.record(
            actor,
            "api_key.updated",
            target=key.key_id,
            detail={"scopes": ",".join(sorted(updated.scopes))},
        )
        return updated

    async def revoke(self, actor: Actor, key_id: str) -> None:
        key = await self._require(key_id)
        self._require_owner_permission(actor, key.owner_id)

        await self._keys.revoke(key_id, self._clock.now())
        await self._audit.record(actor, "api_key.revoked", target=key_id)

    def _require_owner_permission(self, actor: Actor, owner_id: str) -> None:
        """Own keys need `api_key:write_own`; anyone else's needs
        `api_key:write_any`. Checked against the *key's* owner rather than the
        request body, so a caller cannot aim an edit at somebody else's key by
        naming their own id."""
        if owner_id == actor.id:
            self._authz.require(actor, Scope.API_KEY_WRITE_OWN)
            return
        self._authz.require(actor, Scope.API_KEY_WRITE_ANY)

    async def _require(self, key_id: str) -> ApiKey:
        key = await self._keys.get_by_key_id(key_id)
        if key is None:
            # Same error a caller without permission receives, so the endpoint
            # does not confirm which key ids exist.
            raise NotAuthorizedError(detail=f"no key {key_id}")
        return key


def _parse_cidrs(values: Sequence[str]) -> tuple[IPv4Network | IPv6Network, ...]:
    networks: list[IPv4Network | IPv6Network] = []
    for value in values:
        candidate = value.strip()
        if not candidate:
            continue
        try:
            # `strict=False` so `10.0.0.7/24` is accepted as the network it
            # obviously means, rather than rejected for having host bits set.
            networks.append(ip_network(candidate, strict=False))
        except ValueError as exc:
            raise InvalidCidrError(detail=f"unparsable range {candidate!r}") from exc
    return tuple(networks)
