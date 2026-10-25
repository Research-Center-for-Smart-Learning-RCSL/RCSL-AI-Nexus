"""Closing and reopening the platform (#61), the access half.

What this closes today: every entrance refuses everyone except platform
administrators, every non-admin local session dies, API keys and every
inference path (administrators' included) answer 503 `maintenance`, and the
residency reconciler stands down. What it does not yet do is stop work that
was already running in the runtime when the hold landed, or release and later
restore the resident models; those are the coordinator and host supervisor
of #61's later packages. That gap is why entering is behind
`maintenance_enabled`, which is off until they exist and have passed on the
host: a hold that cannot interrupt is not the maintenance #61 asks for, and
must not be offered as one.

Entering and reopening are idempotent rather than conditional on a revision.
A second press of either button, from the same administrator or another, finds
the platform already where it was asked to be and returns that state; only
the message, which two people could be editing at once, is revision-checked.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance import MAX_MESSAGE_LENGTH, MaintenanceState
from app.domain.exceptions import (
    MaintenanceDisabledError,
    MaintenanceError,
    MaintenanceStateConflictError,
    NotAuthorizedError,
)
from app.domain.ports.repositories import MaintenanceRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort


class ManageMaintenance:
    def __init__(
        self,
        maintenance: MaintenanceRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        *,
        enabled: bool,
    ) -> None:
        self._maintenance = maintenance
        self._authz = authz
        self._audit = audit
        self._enabled = enabled

    async def public_status(self) -> MaintenanceState:
        """No actor: this is what the maintenance page polls. The router
        decides which fields of it leave the process."""
        return await self._maintenance.read()

    async def status(self, actor: Actor) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_READ)
        return await self._maintenance.read()

    async def enter(
        self, actor: Actor, *, message: str | None, expected_return_at: datetime | None
    ) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        if not self._enabled:
            raise MaintenanceDisabledError(detail="MAINTENANCE_ENABLED is off")

        closed = await self._maintenance.close(
            changed_by=actor.id,
            message=_clean(message),
            expected_return_at=expected_return_at,
        )
        if closed is None:
            return await self._maintenance.read()

        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_ENTERED,
            target="platform",
            detail={"epoch": str(closed.epoch)},
        )
        return closed

    async def reopen(self, actor: Actor) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        opened = await self._maintenance.reopen(changed_by=actor.id)
        if opened is None:
            return await self._maintenance.read()

        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_REOPENED,
            target="platform",
            detail={"epoch": str(opened.epoch)},
        )
        return opened

    async def set_message(
        self,
        actor: Actor,
        *,
        message: str | None,
        expected_return_at: datetime | None,
        expected_revision: int,
    ) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        saved = await self._maintenance.set_message(
            changed_by=actor.id,
            message=_clean(message),
            expected_return_at=expected_return_at,
            expected_revision=expected_revision,
        )
        if saved is None:
            raise MaintenanceStateConflictError(
                detail=f"revision {expected_revision} is no longer current"
            )
        await self._audit.record(actor, AuditAction.MAINTENANCE_MESSAGE_SET, target="platform")
        return saved

    def _require(self, actor: Actor, scope: Scope) -> None:
        """The scope, and the live role behind it.

        The scopes are admin-only already; the role is checked as well because
        the hold's whole contract is "platform administrators, and nobody
        else", and an API key's actor (role `service`) must never reach here
        whatever a future scope table says.
        """
        self._authz.require(actor, scope)
        if actor.role is not Role.ADMIN:
            raise NotAuthorizedError(detail=f"maintenance needs a platform admin, not {actor.role}")


async def assert_serving(maintenance: MaintenanceRepositoryPort) -> None:
    """Raise `MaintenanceError` while the platform is closed.

    The one check every path that spends the runtime makes: gateway keys,
    administrators' chat and assistant, embeddings, model lifecycle and the
    detached jobs. Platform administrators are not exempt; they keep the
    management screens, not the models.
    """
    state = await maintenance.read()
    if state.admission_closed:
        raise MaintenanceError(detail=f"maintenance epoch {state.epoch}")


def _clean(message: str | None) -> str | None:
    if message is None:
        return None
    message = message.strip()
    if not message:
        return None
    return message[:MAX_MESSAGE_LENGTH]
