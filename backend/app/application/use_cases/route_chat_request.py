"""Resolve a capability to a model and stream the completion.

This is the one place where the streaming contract from
docs/architecture/backend.md section 6 is enforced, so the ordering here is
deliberate rather than incidental:

- the concurrency slot is held for the whole generator lifetime, not just
  the call that creates it;
- usage is recorded in `finally`, so a client that disconnects mid-stream
  still bills what the hardware actually produced;
- cancellation is allowed to propagate, so the runtime adapter can close its
  upstream request instead of generating tokens for nobody;
- a generation is bounded by both a token ceiling and a wall-clock deadline,
  so a slow-but-steady stream cannot hold a concurrency slot indefinitely.

Consumers must wrap iteration in `contextlib.aclosing()`. A `finally` inside
an async generator only runs when the generator is closed, and abandoning one
without closing it leaks a concurrency slot until garbage collection.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import aclosing

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model, RuntimeKind
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import ContextTooLongError, NoAvailableModelError, NotAuthorizedError
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

_TERMINAL_EVENT_DRAIN_LIMIT = 8
"""How many events past the token ceiling to read looking for the terminal one.

The runtime is told `num_predict = ceiling`, so it stops on the same token and
its terminal event — the only place the prompt token count appears — is the
very next one. This is the backstop for a runtime that does not honour that,
so the request cannot be held open by one that keeps streaming. Small on
purpose: it is a guard, not a budget."""


def _context_chars(messages: Sequence[Message], tools: Sequence[ToolDefinition]) -> int:
    """Everything the model will read, in characters.

    A tool definition's `parameters` is arbitrary JSON, so it is measured by
    serialising it rather than by walking it: the length of the text the adapter
    will send is the figure that matters, and a nested schema has no other
    honest measure. The cost is one serialisation of a payload the adapter
    serialises again a few lines later, against a guardrail that runs before any
    hardware is committed.
    """
    total = sum(len(m.content) for m in messages)
    for message in messages:
        total += sum(len(c.name) + len(c.arguments) for c in message.tool_calls)
    for tool in tools:
        total += len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters))
    return total


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
        generation_deadline_seconds: int = 600,
        thinking_default: bool = True,
        monotonic: Callable[[], float] = time.monotonic,
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
        self._generation_deadline_seconds = generation_deadline_seconds
        self._thinking_default = thinking_default
        """What a request that expresses no preference gets. The default lives
        here rather than in the adapter so there is one source for it: an
        adapter holding its own default would disagree with this one the first
        time either changed, and the disagreement would be invisible."""
        self._monotonic = monotonic
        """A monotonic elapsed-time source, injected so the deadline is testable
        without real waiting. Monotonic, not the wall-clock `Clock`, because an
        NTP step must not move a generation's deadline."""

    async def execute(
        self,
        actor: Actor,
        capability: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool | None = None,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """`thinking=None` takes the configured default; True and False are the
        caller's explicit choice.

        Per request rather than per model, because one resident copy has to
        serve both: the registry cannot hold the same weights under two aliases
        (`ix_models_node_ref` is unique on node, runtime and ref), and if it
        could, the memory budget would count 32 GB twice and refuse the second
        load. Unlike `max_tokens` this is not clamped — it costs no hardware,
        and a caller asking a deliberating model to answer directly is asking
        for less work, not more.
        """
        self._authz.require(actor, self.required_scope)

        # Which capability, as opposed to whether inference at all. An API key
        # carries the list it was issued with; a person on an admin entrance
        # carries None and is unrestricted here, their reach being decided by
        # role. Refused rather than routed, and deliberately not folded into
        # the "no available model" answer below: the caller can fix this one,
        # and telling them it is a capacity problem sends them nowhere.
        if not actor.may_use(capability):
            raise NotAuthorizedError(detail=f"key {actor.display} is not issued for {capability}")

        # A ceiling on input as well as output. Context cost grows faster than
        # linearly on unified memory, so a single enormous prompt is a
        # hardware problem in the same way an unbounded generation is, and it
        # arrives before any token has been produced.
        #
        # Tool definitions and prior tool calls count towards it. They are
        # prompt the model reads like any other, and they are the part an agent
        # client grows without bound: leaving them out would have let a caller
        # carry an arbitrary payload past the guardrail in `tools`, which is
        # the one field of an agent request that no person ever types.
        total_chars = _context_chars(messages, tools)
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
                self._generate(
                    actor,
                    capability,
                    target,
                    runtime,
                    messages,
                    max_tokens,
                    # Request, then policy, then deployment. The middle level
                    # exists because the answer is per capability rather than
                    # per deployment: an agent loop on `code` pays the
                    # deliberation cost on every tool round trip, where `chat`
                    # wants it and `assist` cannot afford it at all. Only the
                    # request may be `False` meaningfully, so `is None` is the
                    # test at both levels rather than a truthiness check.
                    self._resolve_thinking(thinking, policy),
                    tools,
                    tool_choice,
                    sampling,
                )
            ) as generation:
                async for chunk in generation:
                    yield chunk

    def _resolve_thinking(self, requested: bool | None, policy: RoutingPolicy) -> bool:
        if requested is not None:
            return requested
        if policy.thinking is not None:
            return policy.thinking
        return self._thinking_default

    async def _generate(
        self,
        actor: Actor,
        capability: str,
        target: Model,
        runtime: ModelRuntimePort,
        messages: Sequence[Message],
        max_tokens: int | None,
        thinking: bool,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        # The caller's request is honoured only where it is stricter than ours.
        # An unbounded generation is a hardware problem, not a client choice.
        ceiling = min(max_tokens or self._max_tokens_ceiling, self._max_tokens_ceiling)

        produced = 0
        prompt_tokens = 0
        drained = 0
        forwarded_terminal = False
        """Whether a terminal chunk reached the *client*, which is not the same
        as the upstream having sent one: past the ceiling the terminal chunk is
        drained for its token count and deliberately not forwarded. Deciding on
        `upstream_finished` instead would leave a truncated stream with no
        terminal frame at all."""

        completed = False
        truncated = False
        upstream_finished = False
        started = self._monotonic()
        deadline = self._generation_deadline_seconds

        try:
            # `aclosing` on the upstream generator is not optional. When a
            # client disconnects, GeneratorExit is thrown at the `yield` below
            # and this generator's `finally` runs, but the runtime's generator
            # would merely be dropped for the garbage collector to close
            # eventually. Its own `finally` is what closes the upstream HTTP
            # request, so without this the runtime keeps generating tokens for
            # a client that already left. This is the same obligation placed
            # on consumers of this use case.
            async with aclosing(
                runtime.generate(
                    target.ref, messages, ceiling, thinking, tools, tool_choice, sampling
                )
            ) as upstream:
                async for chunk in upstream:
                    # Assigned, not accumulated: the runtime reports it once
                    # for the whole request, on the terminal chunk. Summing
                    # would multiply it by the length of the stream.
                    if chunk.prompt_tokens:
                        prompt_tokens = chunk.prompt_tokens
                    if chunk.finish_reason:
                        upstream_finished = True

                    if truncated:
                        # Past the ceiling: consuming, not forwarding.
                        #
                        # Breaking here instead — which is what this did until
                        # the bug below was found — loses the prompt token
                        # count entirely, because the runtime reports it only
                        # on its terminal event and that event had not been
                        # read yet. `max_tokens: 1` in front of a
                        # context-filling prompt then cost one token of quota:
                        # exactly the hole counting prompt tokens was meant to
                        # close, reopened by the ceiling that runs first.
                        #
                        # Draining is cheap and bounded because the runtime was
                        # told `num_predict = ceiling`, so it stops on the same
                        # token and its terminal event is the very next one.
                        # The bound is a backstop for a runtime that ignores
                        # that, not the expected path.
                        if upstream_finished:
                            # The terminal chunk's own count is a reconciliation
                            # against the runtime's authoritative total, so it
                            # is billed. The content chunks skipped on the way
                            # here are not: they were cut off rather than
                            # delivered, and billing for output withheld from
                            # the caller would be a charge for our own limit.
                            produced += chunk.token_count
                            break
                        drained += 1
                        if drained >= _TERMINAL_EVENT_DRAIN_LIMIT:
                            logger.info(
                                "%s did not send a terminal event within %s chunks of the "
                                "ceiling; prompt tokens go unrecorded for this request",
                                target.ref,
                                _TERMINAL_EVENT_DRAIN_LIMIT,
                            )
                            break
                        continue

                    produced += chunk.token_count
                    if chunk.finish_reason:
                        forwarded_terminal = True
                    yield chunk
                    if produced >= ceiling:
                        truncated = True
                        continue
                    # A wall-clock ceiling as well as a token one. A model
                    # producing slowly enough to stay under the per-read timeout
                    # yet below the token ceiling would otherwise hold a
                    # concurrency slot indefinitely; near swap on unified memory
                    # that is the realistic case. Cutting here reports "length"
                    # through the same block below, the honest signal that the
                    # model did not finish.
                    if deadline > 0 and self._monotonic() - started > deadline:
                        truncated = True
                        logger.info(
                            "generation for %s hit the %ss deadline after %s tokens",
                            target.ref,
                            deadline,
                            produced,
                        )
                        break

            # Only when the upstream did not already send a terminal chunk. At
            # the ceiling the two coincide — Ollama is told `num_predict =
            # ceiling`, so its own done chunk arrives on the same token that
            # trips truncation, and the drain above is what reads it — and
            # emitting a second terminal frame put a chunk after the terminal
            # one on the wire for OpenAI clients. The drained terminal chunk is
            # deliberately not forwarded, so this still fires and the client
            # still sees exactly one terminal frame, reporting `length`.
            if truncated and not forwarded_terminal:
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
                        # Zero when the stream did not reach its terminal
                        # chunk, because that is the only place the runtime
                        # reports the figure. A client that disconnects
                        # mid-answer is therefore under-charged for a prompt
                        # the hardware did read. Recording the honest zero
                        # beats inventing a number; closing it needs a count
                        # taken before generation starts, which no runtime
                        # port currently offers. Truncation at the ceiling is
                        # not affected: Ollama's own done chunk arrives on the
                        # same token, so that path still sees it.
                        prompt_tokens=prompt_tokens,
                        latency_ms=int((self._monotonic() - started) * 1000),
                        completed=completed,
                        at=self._clock.now(),
                        # Attributed to the caller's tenant, so per-tenant usage
                        # reads see only their own.
                        tenant_id=actor.tenant_id,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to record usage for actor=%s", actor.display)
