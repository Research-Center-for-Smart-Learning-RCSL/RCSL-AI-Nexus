"""What a maintenance entry does to each node, and how far it has got (P4 on #61).

An entry closes access in one transaction (`maintenance.py`). Releasing the
runtimes cannot be part of it: it means talking to every node agent, and a
node can be slow, unreachable or restarting. So the same transaction records an
operation and one step per node, and the maintenance coordinator in the tailnet
admin carries each step through its phases, writing every result back before it
takes the next. A coordinator that dies is replaced by another that reads where
the last one stopped; the database, not a process, knows what has been done.

**The phases of a node, in order.**

1. `pending`. Nothing done yet.
2. `interrupted`. The agent froze its gate for this epoch and cancelled every
   sender still talking to the runtime. Interrupted attempts are
   `outcome_unknown`, which is truthful.
3. `snapshotted`. What the runtime actually held, read from the runtime, is
   saved: the set P5 restores. Written once and never replaced, so a retry
   cannot overwrite the original with a partly emptied runtime. If the runtime
   could not be observed, `snapshot_error` says so instead; an unobserved
   runtime is never recorded as empty.
4. `reset`. The supervisor restarted the runtime with nothing loaded, with
   witness evidence on both sides, and the unknowns that evidence covers were
   resolved. `accounting` says whether any remain.
5. `verified`. A fresh observation of the new runtime holds no model.

A step that keeps failing stops as `failed` with its error, and the operation
fails with it once no step is still running. The platform stays closed
throughout; an administrator retries from the persisted step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class OperationKind(StrEnum):
    ENTER = "enter"


class OperationStatus(StrEnum):
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    ABANDONED = "abandoned"
    """The hold was lifted, or moved to a later epoch, before the entry
    finished: there is nothing left for it to release."""


class StepPhase(StrEnum):
    PENDING = "pending"
    INTERRUPTED = "interrupted"
    SNAPSHOTTED = "snapshotted"
    RESET = "reset"
    VERIFIED = "verified"


class StepStatus(StrEnum):
    RUNNING = "running"
    FAILED = "failed"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class NodeStep:
    operation_id: str
    node_id: str
    phase: StepPhase
    status: StepStatus
    attempts: int = 0
    interrupt: dict[str, Any] | None = None
    snapshot: list[dict[str, Any]] | None = None
    snapshot_at: datetime | None = None
    snapshot_error: str | None = None
    reset_id: str | None = None
    reset: dict[str, Any] | None = None
    accounting: str | None = None
    verification: dict[str, Any] | None = None
    error: str | None = None
    updated_at: datetime | None = None

    @property
    def snapshot_taken(self) -> bool:
        return self.snapshot is not None or self.snapshot_error is not None


@dataclass(frozen=True, slots=True)
class MaintenanceOperation:
    id: str
    kind: OperationKind
    epoch: int
    status: OperationStatus
    requested_by: str
    owner: str | None = None
    lease_expires_at: datetime | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    steps: tuple[NodeStep, ...] = field(default_factory=tuple)


SNAPSHOT_FIELDS = (
    "name",
    "model",
    "digest",
    "size",
    "size_vram",
    "context_length",
    "expires_at",
    "details",
)
"""What a snapshot keeps of each `/api/ps` entry: the reference and digest
that pin what was loaded, its size, and the context it was loaded with. P5
restores from these, never from the registry's current defaults."""


def snapshot_of(resident: list[Any]) -> list[dict[str, Any]]:
    return [
        {key: entry[key] for key in SNAPSHOT_FIELDS if key in entry}
        for entry in resident
        if isinstance(entry, dict)
    ]
