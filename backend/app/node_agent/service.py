"""Assembling the node agent, and keeping it honest while it runs.

Start-up order is the election order (design R1 on #24): the host lock, then
the node's advisory lock and takeover, and only then a gate that may open. The
gate opens only if no operation on the node is unknown.

A watchdog re-checks both locks every few seconds. Losing either one closes
the gate for good and asks the process to stop; shutdown then waits until
every admitted task has reached terminal evidence (design U1), because the
host lock must outlive anything this process could still send.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass, field

import asyncpg

from app.adapters.runtime.ollama_adapter.encoding import _keep_alive
from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.node_agent.dispatch import Dispatcher, GateState
from app.node_agent.election import Elected, claim, still_elected
from app.node_agent.lock_domain import HostLock, initialise, kernel_boot_id
from app.node_agent.relay import OllamaRelay
from app.node_agent.resolution import Resolutions, Witness
from app.node_agent.settings import AgentSettings
from app.node_agent.store import OperationStore

logger = logging.getLogger(__name__)


@dataclass
class Agent:
    settings: AgentSettings
    host_lock: HostLock
    election_conn: asyncpg.Connection
    elected: Elected
    pool: asyncpg.Pool
    store: OperationStore
    dispatcher: Dispatcher
    relay: OllamaRelay
    counter: GgufTokenCounter | None
    resolutions: Resolutions
    keep_alive: str | int
    terminate: Callable[[], None] = field(default=lambda: os.kill(os.getpid(), signal.SIGTERM))
    """How a lost role ends the process. SIGTERM to ourselves, not a fork or
    exec: uvicorn's graceful shutdown runs `stop`, which waits for admitted
    work before the process, and with it the host lock, goes away."""
    _watchdog: asyncio.Task[None] | None = None

    async def watch(self) -> None:
        while True:
            await asyncio.sleep(self.settings.watchdog_s)
            if not self.host_lock.still_held():
                await self._lost("host lock file unlinked or replaced")
                return
            if not await still_elected(self.election_conn, self.elected.backend_pid):
                await self._lost("election session lost")
                return

    async def _lost(self, reason: str) -> None:
        await self.dispatcher.lose_role(reason)
        await self.store.audit(
            "role_lost",
            None,
            {
                "reason": reason,
                "generation": self.elected.ownership.generation,
                "boot_id": self.elected.ownership.boot_id,
                "admitted": self.dispatcher.admitted,
            },
        )
        self.terminate()


async def start(settings: AgentSettings) -> Agent:
    initialise(settings.lock_dir)
    host_lock = HostLock.acquire(settings.lock_dir)
    election_conn = await asyncpg.connect(settings.dsn)
    try:
        elected = await claim(
            election_conn, settings.node_id, host_lock, kernel_boot_id=kernel_boot_id()
        )
    except BaseException:
        await election_conn.close()
        raise
    logger.info(
        "elected for node %s: generation %s, %s orphaned operations now unknown, %s unsent",
        settings.node_id,
        elected.ownership.generation,
        elected.converted_unknown,
        elected.converted_unsent,
    )
    pool = await asyncpg.create_pool(settings.dsn, min_size=1, max_size=8)
    store = OperationStore(pool, elected.ownership)
    dispatcher = Dispatcher(
        store,
        max_inflight=settings.max_inflight,
        max_queued=settings.max_queued,
        host_lock_held=host_lock.still_held,
    )
    witness = Witness(
        settings.witness_out,
        settings.witness_challenge,
        expected_endpoint=settings.witness_endpoint,
    )
    agent = Agent(
        settings=settings,
        host_lock=host_lock,
        election_conn=election_conn,
        elected=elected,
        pool=pool,
        store=store,
        dispatcher=dispatcher,
        relay=OllamaRelay(settings.runtime_base_url, timeout_s=settings.request_timeout_s),
        counter=GgufTokenCounter(settings.models_root) if settings.models_root else None,
        resolutions=Resolutions(dispatcher, store, witness),
        keep_alive=_keep_alive(settings.keep_alive),
    )
    state = await dispatcher.reopen()
    if state is GateState.BLOCKED:
        logger.warning("node %s is blocked by unknown operations", settings.node_id)
    agent._watchdog = asyncio.create_task(agent.watch())
    return agent


async def stop(agent: Agent) -> None:
    """Admit nothing more, then wait for admitted work to reach terminal evidence."""
    await agent.dispatcher.lose_role("shutdown")
    await agent.dispatcher.wait_idle()
    if agent._watchdog is not None:
        agent._watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await agent._watchdog
    await agent.relay.aclose()
    await agent.pool.close()
    await agent.election_conn.close()
    # The host lock is not released here: it goes with the process.
