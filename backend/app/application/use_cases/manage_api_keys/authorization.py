"""API-key authorization and policy coordination."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.exceptions import (
    ApiKeyLifetimeError,
    ApiKeyStateConflictError,
    NotAuthorizedError,
)
from app.domain.ports.repositories import (
    ApiKeyRepositoryPort,
    UsageRepositoryPort,
    UserRepositoryPort,
)
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.domain.services.api_key_service import ApiKeyService
from app.shared.clock import Clock


class ApiKeyPolicyMixin:
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
        max_lifetime_days: int = 3650,
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
            raise ApiKeyStateConflictError(detail=f"expiry {expires_at} is not in the future")
        if expires_at > now + self._max_lifetime:
            # The one refusal on this surface that reached a caller and told
            # them nothing they could act on. On 2026-08-17 an operator sent
            # this seven times in three minutes with 2029, then 2028, then
            # 2027 -- each beyond the maximum, each answered with a message
            # about *models* because this code was the platform's general 409
            # -- and concluded the capability edit beside it was what had
            # failed. `ApiKeyLifetimeError` carries the figure, so the number
            # they are being held to arrives with the refusal.
            raise ApiKeyLifetimeError(
                self._max_lifetime.days,
                detail=f"expiry {expires_at} is beyond the {self._max_lifetime.days} day maximum",
            )

    def _assert_default_capability(self, default: str | None, scopes: Collection[str]) -> None:
        """A substitution within the key's own list, or nothing.

        The whole safety of the field is here: whatever a caller names in
        `model`, a key with a default reaches exactly the capabilities it was
        issued for, so the setting can shorten the path to one of them and can
        never add one. Refused rather than silently dropped, because a key
        whose stated default does nothing is the shape an operator reads as
        "the platform ignored me".
        """
        if default is None:
            return
        if default not in scopes:
            raise ApiKeyStateConflictError(
                detail=(
                    f"default capability {default} is not one of this key's "
                    f"capabilities {sorted(scopes)}"
                )
            )

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
