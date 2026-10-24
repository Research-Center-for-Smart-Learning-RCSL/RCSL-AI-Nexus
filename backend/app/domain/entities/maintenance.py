"""The platform-wide maintenance hold (#61).

One row, held in PostgreSQL, because every process has to agree on whether the
platform serves: the gateway, both admin entrances and, later, the node agent.
A process-local flag or a cache entry could disagree with the others, and a
cache entry is also writable by the gateway, which must never be able to lift
the hold.

**The epoch is what revokes sessions.** Each entry increments it, and a local
session records the epoch current when it was issued. A session belonging to
anyone but a platform administrator is honoured only if it was issued at or
after the latest entry, so every non-admin session that existed when the
platform closed stays dead after it reopens, on every worker, without the
session store having to enumerate anything. A login that read the epoch just
before an entry committed carries the older number and dies the same way,
which is what closes the race between signing in and closing. The epoch never
decreases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MaintenancePhase(StrEnum):
    """`normal` serves; `maintenance` is closed. The finer phases #61 plans
    (entering, restoring, verifying) arrive with the coordinator that can tell
    them apart; until then a closed platform is simply closed."""

    NORMAL = "normal"
    MAINTENANCE = "maintenance"


MAX_MESSAGE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class MaintenanceState:
    admission_closed: bool
    phase: MaintenancePhase
    epoch: int
    revision: int
    """Bumped by every change, so an edit made against a stale read is refused
    rather than silently overwriting what another administrator just did."""

    message: str | None = None
    expected_return_at: datetime | None = None
    changed_by: str | None = None
    changed_at: datetime | None = None

    @property
    def serving(self) -> bool:
        return not self.admission_closed

    def session_valid(self, session_epoch: int, *, platform_admin: bool) -> bool:
        """Whether a local session issued at `session_epoch` may still be used.

        Platform administrators keep theirs through an entry; everybody else's
        dies with it, and does not come back when the platform reopens.
        """
        return platform_admin or session_epoch >= self.epoch


NORMAL = MaintenanceState(
    admission_closed=False, phase=MaintenancePhase.NORMAL, epoch=0, revision=0
)
"""What a deployment reads before the migration has written the row. Only
tests construct it; the migration seeds the real one."""
