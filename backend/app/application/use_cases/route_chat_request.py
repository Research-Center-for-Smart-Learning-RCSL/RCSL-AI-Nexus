"""Resolve a capability to a model and stream the completion.

This is the one place where the streaming contract from
docs/architecture/backend.md section 6 is enforced, so the ordering here is
deliberate rather than incidental:

- the concurrency slot is held for the whole generator lifetime, not just
  the call that creates it;
- usage is recorded in `finally`, so a client that disconnects mid-stream
  still bills what the hardware actually produced;
- cancellation is allowed to propagate, so the runtime adapter can close its
  upstream request instead of generating tokens for nobody.

Consumers must wrap iteration in `contextlib.aclosing()`. A `finally` inside
an async generator only runs when the generator is closed, and abandoning one
without closing it leaks a concurrency slot until garbage collection.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing

from app.domain.entities.actor import Actor
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import RuntimeKind
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import NoAvailableModelError
from app.domain.ports.infrastructure_ports import ConcurrencyLimiterPort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    RoutingPolicyRepositoryPort,
    UsageRepositoryPort,
)
from app.domain.services.routing_service import RoutingService
from app.shared.clock import Clock


class RouteChatRequest:
    def __init__(
        self,
        policies: RoutingPolicyRepositoryPort,
        models: ModelRepositoryPort,
        nodes: NodeRepositoryPort,
        usage: UsageRepositoryPort,
        runtimes: dict[RuntimeKind, ModelRuntimePort],
        routing: RoutingService,
        concurrency: ConcurrencyLimiterPort,
        clock: Clock,
        max_tokens_ceiling: int,
    ) -> None:
        self._policies = policies
        self._models = models
        self._nodes = nodes
        self._usage = usage
        self._runtimes = runtimes
        self._routing = routing
        self._concurrency = concurrency
        self._clock = clock
        self._max_tokens_ceiling = max_tokens_ceiling

    async def execute(
        self,
        actor: Actor,
        capability: str,
        messages: Sequence[Message],
        api_key_id: str | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        policy = await self._policies.get(capability)
        if policy is None:
            raise NoAvailableModelError(detail=f"no policy for capability={capability}")

        models = {m.alias: m for m in await self._models.list_all()}
        nodes = {n.id: n for n in await self._nodes.list_all()}
        target = self._routing.select(policy, models, nodes)

        runtime = self._runtimes.get(target.runtime)
        if runtime is None:
            raise NoAvailableModelError(detail=f"no adapter for runtime={target.runtime}")

        produced = 0
        completed = False
        started = time.monotonic()

        async with self._concurrency.slot():
            try:
                # `aclosing` on the upstream generator is not optional. When a
                # client disconnects, GeneratorExit is thrown at the `yield`
                # below and this generator's `finally` runs, but the runtime's
                # generator would merely be dropped for the garbage collector
                # to close eventually. Its own `finally` is what closes the
                # upstream HTTP request, so without this the runtime keeps
                # generating tokens for a client that already left. This is
                # the same obligation placed on consumers of this use case.
                async with aclosing(runtime.generate(target.ref, messages)) as upstream:
                    async for chunk in upstream:
                        produced += chunk.token_count
                        yield chunk
                        if produced >= self._max_tokens_ceiling:
                            # Hard ceiling, applied regardless of what the
                            # client asked for. Bounds a runaway generation.
                            break
                completed = True
            finally:
                # Runs on normal completion, on client disconnect, and on
                # error. Recording here is what makes partial output billable.
                await self._usage.record(
                    UsageRecord(
                        id=str(uuid.uuid4()),
                        actor_id=actor.id,
                        api_key_id=api_key_id,
                        capability=capability,
                        model_alias=target.alias,
                        tokens=produced,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        completed=completed,
                        at=self._clock.now(),
                    )
                )
