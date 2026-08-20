"""Model lifecycle state contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.domain.entities.model import Model, ModelState


class ModelStateCommitterPort(Protocol):
    """Reads and writes a model's state in its own short transaction.

    `commit` surviving the request's rollback is what keeps a failed load's
    ERROR from being lost with it; see adapters/persistence/model_state.py.
    `get` is used by the detached download task, which must not hold a session
    across the multi-hour pull.
    """

    async def get(self, model_id: str) -> Model | None: ...

    async def commit(self, model_id: str, state: ModelState) -> None: ...


def _with_state(model: Model, state: ModelState) -> Model:
    """The model as it is after an intent write, observation included.

    `set_state` clears the observation, so returning `replace(model, state=...)`
    would answer with the observation as it was *before* the write — telling the
    caller the runtime reports something the same request just invalidated. The
    models table renders a mismatch between the two as a divergence in red, so
    the stale value shows the operator a conflict that does not exist.
    """
    return replace(
        model, state=state, observed_state=None, observed_memory_gb=None, observed_at=None
    )


DELETABLE_STATES = frozenset({ModelState.NOT_DOWNLOADED, ModelState.DOWNLOADED, ModelState.ERROR})
