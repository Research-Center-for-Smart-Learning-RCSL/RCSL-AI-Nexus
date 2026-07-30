"""Committing a model's terminal state independently of the request.

`load` and `unload` write a transient state, call the runtime, and on failure
write a terminal one and raise. But the raise is what triggers `session_scope`
to roll back, so the terminal write is lost with it: a load that failed left
the registry saying `downloaded` while the weights might be resident, and the
memory budget then under-counted by the size of that model — the exact
over-commit section 4.3 exists to prevent.

The audit adapter has the same shape and the same answer: a write that must
survive the request's rollback goes in its own transaction. This is that, for
model state.

It is used only for the failure transitions and for `LOADING`. The success
transition rides the request transaction as before, because if that commit
fails the operation genuinely did not happen and the state should not claim
it did.
"""

from __future__ import annotations

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import ModelRow
from app.domain.entities.model import Model, ModelState

logger = logging.getLogger(__name__)


class ModelStateCommitter:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, model_id: str) -> Model | None:
        """A read in its own short transaction.

        The download task uses this rather than holding a session open for the
        whole pull. Progress goes to the cache, so between this read and the
        final state write the task touches no database connection at all — the
        idle-in-transaction hold that pinned one of fifteen connections for
        hours, and blocked VACUUM, is gone.
        """
        async with self._sessions() as session:
            row = await session.get(ModelRow, model_id)
            return m.model_to_domain(row) if row else None

    async def commit(self, model_id: str, state: ModelState) -> None:
        try:
            async with self._sessions() as session:
                # The observation goes null with the intent write, for the reason
                # `PostgresModelRepository.set_state` spells out: readers rank
                # observation over intent, so one taken before this transition
                # would outrank the transition itself.
                await session.execute(
                    update(ModelRow)
                    .where(ModelRow.id == model_id)
                    .values(
                        state=state.value,
                        observed_state=None,
                        observed_memory_gb=None,
                        observed_at=None,
                    )
                )
                await session.commit()
        except Exception:
            # A durable-state write that fails has nowhere to report: its
            # caller is already raising the error that prompted it, or has
            # already returned. Logging is the floor; the deploy-time
            # reconciliation is the backstop for a state left wrong here.
            logger.exception("model_state_commit_failed model=%s state=%s", model_id, state.value)
