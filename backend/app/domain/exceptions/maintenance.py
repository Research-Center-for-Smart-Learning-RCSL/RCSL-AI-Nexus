"""Maintenance-hold domain errors (#61)."""

from __future__ import annotations

from .base import DomainError, StateConflictError

MAINTENANCE_RETRY_AFTER_SECONDS = 60
"""What a refused caller is told to wait. A maintenance window has no fixed
end the platform could promise, so this is a polling interval rather than a
prediction; the expected return time, when an administrator gave one, is on
the public status instead."""


class MaintenanceError(DomainError):
    """503: the platform is closed for maintenance, and this operation waits for
    it to reopen.

    Its own code rather than `no_available_model` or `overloaded`, because the
    remedy differs from both. Nothing is broken and nothing is busy: retrying
    sooner cannot help, and a client that branches on the code can show the
    maintenance message instead of an outage. No key is revoked to produce
    this; the same key works again once the platform reopens.
    """

    code = "maintenance"
    public_message = "The platform is closed for maintenance. Try again later."

    def __init__(
        self,
        retry_after_seconds: int = MAINTENANCE_RETRY_AFTER_SECONDS,
        detail: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds


class MaintenanceStateConflictError(StateConflictError):
    code = "maintenance_state_conflict"
    public_message = "The maintenance state changed since it was read. Reload and try again."


class MaintenanceDisabledError(StateConflictError):
    """Entering maintenance is switched off on this deployment.

    Until the forced interruption and verified restoration of #61 are built and
    accepted on the host, a hold closes access but cannot stop work already
    running in the runtime, so it is not offered as maintenance. Reopening is
    never refused by this: a hold left by an earlier build has to be liftable.
    """

    code = "maintenance_disabled"
    public_message = "Maintenance mode is not enabled on this deployment."
