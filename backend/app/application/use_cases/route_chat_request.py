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

import logging
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import RuntimeKind
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import ContextTooLongError, NoAvailableModelError
from app.domain.ports.infrastructure_ports import ConcurrencyLimiterPort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    RoutingPolicyRepositoryPort,
    UsageRepositoryPort,
)
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.services.routing_service import RoutingService
from app.shared.clock import Clock

logger = logging.getLogger(__name__)


class RouteChatRequest:
    required_scope = Scope.CHAT_USE

    def __init__(
        self,
        policies: RoutingPolicyRepositoryPort,
        models: ModelRepositoryPort,
        nodes: NodeRepositoryPort,
        usage: UsageRepositoryPort,
        runtimes: dict[RuntimeKind, ModelRuntimePort],
        routing: RoutingService,
        concurrency: ConcurrencyLimiterPort,
        authz: AuthorizationPort,
        clock: Clock,
        max_tokens_ceiling: int,
        max_context_chars: int = 4 * 32768,
    ) -> None:
        self._policies = policies
        self._models = models
        self._nodes = nodes
        self._usage = usage
        self._runtimes = runtimes
        self._routing = routing
        self._concurrency = concurrency
        self._authz = authz
        self._clock = clock
        self._max_tokens_ceiling = max_tokens_ceiling
        self._max_context_chars = max_context_chars
        """Characters, not tokens: counting tokens would mean loading the
        model's tokeniser here, and a rough bound applied before any work
        starts is worth more than an exact one applied later."""

    async def execute(
        self,
        actor: Actor,
        capability: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self._authz.require(actor, self.required_scope)

        # A ceiling on input as well as output. Context cost grows faster than
        # linearly on unified memory, so a single enormous prompt is a
        # hardware problem in the same way an unbounded generation is, and it
        # arrives before any token has been produced.
        total_chars = sum(len(m.content) for m in messages)
        if total_chars > self._max_context_chars:
            raise ContextTooLongError(
                detail=f"{total_chars} characters exceeds the configured limit"
            )

        # The concurrency slot is taken before any database work. Doing the
        # routing reads first would pin a connection for the whole generation,
        # so a pool of 15 would queue behind a semaphore of 2 and fail on
        # checkout rather than shedding load at the semaphore as intended.
        async with self._concurrency.slot():
            policy = await self._policies.get(capability)
            if policy is None:
                raise NoAvailableModelError(detail=f"no policy for capability={capability}")

            models = {m.alias: m for m in await self._models.list_all()}
            nodes = {n.id: n for n in await self._nodes.list_all()}
            target = self._routing.select(policy, models, nodes)

            runtime = self._runtimes.get(target.runtime)
            if runtime is None:
                raise NoAvailableModelError(detail=f"no adapter for runtime={target.runtime}")

            # `aclosing` again, for the same reason it is needed one layer
            # down: a bare `async for` over a generator leaves it for the
            # garbage collector when this one is closed, so the inner
            # `finally` (which records usage and closes the upstream request)
            # would not run promptly. Splitting a generator in two reintroduces
            # this every time.
            async with aclosing(
                self._generate(actor, capability, target, runtime, messages, max_tokens)
            ) as generation:
                async for chunk in generation:
                    yield chunk

    async def _generate(
        self,
        actor: Actor,
        capability: str,
        target,
        runtime: ModelRuntimePort,
        messages: Sequence[Message],
        max_tokens: int | None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        # The caller's request is honoured only where it is stricter than ours.
        # An unbounded generation is a hardware problem, not a client choice.
        ceiling = min(max_tokens or self._max_tokens_ceiling, self._max_tokens_ceiling)

        produced = 0
        completed = False
        truncated = False
        upstream_finished = False
        started = time.monotonic()

        try:
            # `aclosing` on the upstream generator is not optional. When a
            # client disconnects, GeneratorExit is thrown at the `yield` below
            # and this generator's `finally` runs, but the runtime's generator
            # would merely be dropped for the garbage collector to close
            # eventually. Its own `finally` is what closes the upstream HTTP
            # request, so without this the runtime keeps generating tokens for
            # a client that already left. This is the same obligation placed
            # on consumers of this use case.
            async with aclosing(runtime.generate(target.ref, messages, ceiling)) as upstream:
                async for chunk in upstream:
                    produced += chunk.token_count
                    if chunk.finish_reason:
                        upstream_finished = True
                    yield chunk
                    if produced >= ceiling:
                        truncated = True
                        break

            # Only when the upstream did not already send a terminal chunk. At
            # the ceiling the two coincide — Ollama is told `num_predict =
            # ceiling`, so its own done chunk arrives on the same token that
            # trips truncation — and emitting a second terminal frame put a
            # chunk after the terminal one on the wire for OpenAI clients.
            if truncated and not upstream_finished:
                # Report truncation honestly. Reporting "stop" would tell an
                # OpenAI client the model finished, and those clients decide
                # whether to continue a reply on exactly this field.
                yield CompletionChunk(delta="", finish_reason="length", token_count=0)
            completed = not truncated
        finally:
            # Runs on normal completion, on client disconnect, and on error.
            # Recording here is what makes partial output billable.
            #
            # Guarded because this sits in the `finally` of a generator: an
            # exception raised here would replace whatever was already in
            # flight, and being a non-DomainError it would escape the router's
            # handler, truncating the body with neither an error frame nor a
            # terminator. Billing failures are logged, not propagated.
            try:
                await self._usage.record(
                    UsageRecord(
                        id=str(uuid.uuid4()),
                        actor_id=actor.id,
                        api_key_id=actor.api_key_id,
                        capability=capability,
                        model_alias=target.alias,
                        tokens=produced,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        completed=completed,
                        at=self._clock.now(),
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to record usage for actor=%s", actor.display)
