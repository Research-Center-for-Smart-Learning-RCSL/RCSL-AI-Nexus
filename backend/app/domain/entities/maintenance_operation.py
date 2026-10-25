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

**A restore (P5) has its own operation**, made from a succeeded entry, with
each node's snapshot copied into its step when it is created:

1. `pending`. Loading: largest first, one model at a time, and the whole node
   observed again after every load, because a large load can evict a sibling
   restored before it. Bounded by the reconciler's repair rounds.
2. `loaded`. Every saved model is resident with its recorded digest and
   context, and nothing else is.
3. `probed`. Each model answered a bounded check: a vector from an embedding
   model, a token from any other. Observed again after, since a check can
   change what is resident.
4. `verified`. Observed once more; then, when every node is verified, one
   transaction reopens the platform and ends the restore. No node reopens on
   its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class OperationKind(StrEnum):
    ENTER = "enter"
    RESTORE = "restore"


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
    LOADED = "loaded"
    PROBED = "probed"
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


def resident_matches(saved: dict[str, Any], resident: list[dict[str, Any]]) -> bool:
    """Whether `resident` holds what `saved` recorded: the same model, the
    same weights and the same loaded context, where the snapshot knew them."""
    for entry in resident:
        if entry.get("name") != saved.get("name"):
            continue
        if saved.get("digest") and entry.get("digest") != saved.get("digest"):
            return False
        context = saved.get("context_length")
        return not context or entry.get("context_length") == context
    return False


def restore_order(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Largest first, as the reconciler restores (#49): the large model is the
    one that cannot fit once the small ones are placed."""
    return sorted(snapshot, key=lambda m: (-int(m.get("size") or 0), str(m.get("name"))))
