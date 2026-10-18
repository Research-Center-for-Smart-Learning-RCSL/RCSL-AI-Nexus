"""The rules the residency reconciler acts on (#49 §2, final spec §3 on #24).

No I/O. The application loop asks these questions of committed observations;
keeping them here lets the memory budget and the reconciler agree on what a
positive absence is, and lets each rule be tested without a runtime.

Only Ollama is reconciled: it reports residency. MLX cannot, so it gets no
automatic reload and its memory is charged on intent, as before.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.domain.entities.model import Model, ModelState, RuntimeKind
from app.domain.services.routing_service import RESIDENCY_MAX_AGE_SECONDS

REQUIRED_ABSENT_OBSERVATIONS = 2
"""Consecutive positive `downloaded` observations before a model is restored.
A failed, missing or stale probe is not evidence and restarts the count."""

MAX_REPAIR_ROUNDS = 2
"""Rounds after the first in one pass, for desired models a load evicted."""

GIVE_UP_AFTER_WASTED_PASSES = 4
"""Consecutive failed passes that did load weights, for one unchanged intent,
before the reconciler stops restoring that node. A desired set that cannot
co-reside would otherwise reload 30-40 GB every 15 minutes for ever. An intent
change on the node (any Load, Unload or residency-intent write bumps a
version), the whole desired set observed resident, or an admin restart starts
it again."""

BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 15 * 60.0

TRANSIENT_STATES = frozenset({ModelState.DOWNLOADING, ModelState.LOADING, ModelState.UNLOADING})
"""A lifecycle operation is in flight on the model: someone else's, so wait."""


def backoff_seconds(failures: int) -> float:
    """`30 s × 2^n`, capped at 15 minutes; n counts the failed passes before
    this one, so the first failure waits 30 seconds."""
    n = max(failures - 1, 0)
    # Capped before the power can grow without bound on a long outage.
    return min(BACKOFF_BASE_SECONDS * float(2 ** min(n, 16)), BACKOFF_CAP_SECONDS)


def _fresh(model: Model, now: datetime) -> bool:
    if model.observed_state is None or model.observed_at is None:
        return False
    age = (now - model.observed_at).total_seconds()
    return 0 <= age <= RESIDENCY_MAX_AGE_SECONDS


def observed_absent(model: Model, now: datetime) -> bool:
    """A fresh, positive observation that the weights are on disk and not held."""
    return _fresh(model, now) and model.observed_state is ModelState.DOWNLOADED


def observed_resident(model: Model, now: datetime) -> bool:
    return _fresh(model, now) and model.observed_state is ModelState.LOADED


def residency_mismatch(model: Model, now: datetime) -> bool:
    """Wanted resident, and not shown resident by the evidence routing uses.

    Ollama needs a fresh positive `loaded` observation, as routing does since
    #57; unknown or stale evidence is a mismatch, not a pass. MLX cannot report
    residency, so, again as routing does, its intent stands in. A model whose
    weights are gone is still a mismatch: the reconciler skips it, which is
    exactly why someone has to be told.
    """
    if not model.desired_resident:
        return False
    if model.runtime is RuntimeKind.OLLAMA:
        return not observed_resident(model, now)
    return (model.observed_state or model.state) is not ModelState.LOADED


def restorable(model: Model, now: datetime) -> bool:
    """Wanted resident, and not freshly reported as having no weights on disk.

    A model whose weights are gone needs a download, which the reconciler
    never starts; counting it as missing would fail every pass on that node
    and hold back the models that can be restored.
    """
    if not model.desired_resident or model.runtime is not RuntimeKind.OLLAMA:
        return False
    return not (_fresh(model, now) and model.observed_state is ModelState.NOT_DOWNLOADED)


def restore_order(models: Iterable[Model]) -> list[Model]:
    """Largest declared footprint first (E2 on #24).

    On the production host gemma4-31b-q8's scheduler over-predicts its size
    (about 70.9 GiB against 33.5 resident), so loading it after the smaller
    models evicts them. The alias breaks ties so the order is reproducible.
    """
    return sorted(models, key=lambda m: (-m.resource_profile.memory_gb, m.alias))


def charges_memory(model: Model, now: datetime) -> bool:
    """Whether the memory budget counts this model (final spec §3, Occupancy).

    Charged: a model observed resident; one mid-load, whose operation has not
    resolved; and, on Ollama, one whose residency is unknown or stale, at the
    last trustworthy value, which is the lifecycle intent. A fresh positive
    `downloaded` observation is not charged: the runtime has just said it
    holds nothing for it. MLX cannot say, so it is charged on intent alone.
    """
    if model.state is ModelState.LOADING:
        return True
    if model.runtime is RuntimeKind.OLLAMA and _fresh(model, now):
        return model.observed_state is ModelState.LOADED
    return model.state is ModelState.LOADED or model.observed_state is ModelState.LOADED


class AbsenceEvidence:
    """Counts consecutive positive `downloaded` observations per model.

    An observation counts once, by its capture time: the reconciler may look
    more often than the heartbeat writes, and re-reading one answer is not a
    second answer. A gap longer than the freshness window means an answer may
    have been missed (a failed probe clears the stamp and the next success
    writes a new one), so the count restarts rather than spanning it.
    """

    def __init__(self) -> None:
        self._seen: dict[str, tuple[datetime, int]] = {}

    def record(self, model: Model, now: datetime) -> int:
        if not observed_absent(model, now) or model.observed_at is None:
            self._seen.pop(model.id, None)
            return 0
        previous = self._seen.get(model.id)
        if previous is not None and previous[0] == model.observed_at:
            return previous[1]
        count = 1
        if previous is not None:
            gap = (model.observed_at - previous[0]).total_seconds()
            if 0 < gap <= RESIDENCY_MAX_AGE_SECONDS:
                count = previous[1] + 1
        self._seen[model.id] = (model.observed_at, count)
        return count

    def forget(self, model_id: str) -> None:
        self._seen.pop(model_id, None)
