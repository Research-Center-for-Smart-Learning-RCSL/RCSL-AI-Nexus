"""One load at a time per node, across processes (#49 §2).

A session advisory lock on a dedicated connection that is idle, not in a
transaction, while the holder works. The residency reconciler holds it for a
whole pass and an operator's Load for its own duration, so two loads on the
same node never pass the memory budget together.

It is only ever tried, never waited for. A holder that waited could be
waiting on a transaction of its own caller, which is the kind of deadlock the
operator Load once had. The caller is told the node is busy and skips or
refuses instead.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

NODE_LOAD_NAMESPACE = 0x4E58_0003
"""First key of the per-node session advisory lock; the agent's election and
dispatch locks use ...0001 and ...0002."""


class PostgresNodeSerialisation:
    def __init__(self, engine: Callable[[], AsyncEngine]) -> None:
        # A provider, so building a use case never needs the engine until a
        # load actually takes the lock.
        self._engine = engine

    @asynccontextmanager
    async def hold(self, node_id: str) -> AsyncIterator[bool]:
        async with self._engine().connect() as connection:
            held = bool(
                (
                    await connection.execute(
                        text("SELECT pg_try_advisory_lock(:ns, hashtext(:node))"),
                        {"ns": NODE_LOAD_NAMESPACE, "node": node_id},
                    )
                ).scalar_one()
            )
            # A session lock survives the commit; the connection then waits
            # outside any transaction for as long as the holder works.
            await connection.commit()
            try:
                yield held
            finally:
                if held:
                    try:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(:ns, hashtext(:node))"),
                            {"ns": NODE_LOAD_NAMESPACE, "node": node_id},
                        )
                        await connection.commit()
                    except BaseException:
                        # Never back to the pool still holding the node: a
                        # discarded connection takes its session locks with it.
                        logger.warning("node lock release failed node=%s", node_id)
                        with contextlib.suppress(Exception):
                            await connection.invalidate()
                        raise
