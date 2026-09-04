"""Thin route selection and generation-session orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import aclosing

from app.application.use_cases.list_capabilities import ListCapabilities
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model, RuntimeKind
from app.domain.exceptions import (
    COUNT_BY_LOWER_BOUND,
    CapabilityNotIssuedError,
    ContextTooLongError,
    NoAvailableModelError,
)
from app.domain.ports.infrastructure_ports import ConcurrencyLimiterPort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    PromptLogWriterPort,
    RoutingPolicyRepositoryPort,
    UsageRepositoryPort,
)
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.ports.token_counter_port import TokenCounterPort
from app.domain.services.routing_service import RoutingService
from app.shared.clock import Clock

from .compaction import try_compact
from .diagnostics import _warn_if_tools_dominate
from .estimates import _counted_phrase, _floor_composition, _floor_prompt_tokens
from .generation_session import GenerationSessionMixin
from .guardrails import PromptGuardrailsMixin

logger = logging.getLogger("app.application.use_cases.route_chat_request")


class RouteChatRequest(PromptGuardrailsMixin, GenerationSessionMixin):
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
        capabilities: ListCapabilities,
        tokens: TokenCounterPort | None = None,
        prompt_logs: PromptLogWriterPort | None = None,
        request_id: Callable[[], str | None] = lambda: None,
        max_context_tokens: int = 32768,
        generation_deadline_seconds: int = 600,
        thinking_default: bool = True,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policies = policies
        self._models = models
        self._nodes = nodes
        self._usage = usage
        self._tokens = tokens
        """The counter that reads the target's own vocabulary, or None.

            Optional for the same reason `prompt_logs` is, and defaulting the same
            way: a build that does not wire it counts characters, which is what
            every build did before 2026-08-17. What it must never become is a
            required port with a no-op implementation, because then "this
            deployment is not counting exactly" would be a fact about an adapter
            nobody reads instead of a `None` in the composition root.
            """

        self._prompt_logs = prompt_logs
        """Where a §9.2 transcript goes when a debug window is open, or None.

            A writer with its own transaction, not the repository the read path
            uses. The distinction is load-bearing: this write happens in a
            `finally` that runs when the request has *failed*, which is the request
            a debug window is opened for, and staging it on the request session
            meant the failure rolled it back.

            Optional, and the default is the safe direction rather than the
            convenient one: a build that does not wire this records nothing, which
            is what the platform does by default anyway. The opposite arrangement —
            a required port with a no-op implementation — would put "nothing is
            recorded" behind an adapter somebody could replace without touching
            this file.
            """

        self._request_id = request_id
        """How the transcript learns which request it belongs to.

            A callable injected here rather than a parameter on `execute`, because
            there are four call sites across three routers and a fifth would arrive
            without it — leaving transcripts that cannot be found from the error
            the caller quoted, which is the one lookup this table exists to serve.
            The value lives in a contextvar in the interfaces layer; the
            composition root, whose job is knowing about every layer, is what
            connects the two.
            """
        self._runtimes = runtimes
        self._routing = routing
        self._concurrency = concurrency
        self._capabilities = capabilities
        """Read only when refusing, to tell the caller what they may ask for.

            The use case rather than a second query over `policies`: the answer is
            `servable ∩ issuable ∩ this key's own list`, and `list_capabilities.py`
            says in as many words that deriving it twice is how the two come to
            disagree. It costs one read on a path that is already ending, and
            nothing at all on the path that succeeds.
            """
        self._authz = authz
        self._clock = clock
        self._max_tokens_ceiling = max_tokens_ceiling
        self._max_context_tokens = max_context_tokens
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
        #
        # A key may name a substitute for this case, and `capability_for`
        # returns it. Everything below reads `served` rather than the value the
        # caller sent, so the policy that runs, the model that is chosen, the
        # vocabulary the prompt is counted in and the capability written to
        # `usage_records` are all the one that actually did the work.
        served = actor.capability_for(capability)
        if served is None:
            # Named in the response, unlike every other refusal here. The
            # caller sent this value and the list is what `GET /v1/models`
            # already returns them, so nothing is disclosed that they could not
            # have asked for directly — and without it the reason exists only
            # in this deployment's log, where an integrator cannot reach it.
            # See `CapabilityNotIssuedError`.
            raise CapabilityNotIssuedError(
                capability=capability,
                available=await self._capabilities.execute(actor),
                detail=f"key {actor.display} is not issued for {capability}",
            )

        if served != capability:
            # Logged at every substitution, and deliberately not only when the
            # header is read. A default is the one setting on a key that makes
            # the platform serve something other than what was asked for, and
            # the whole argument for allowing it per key rather than globally
            # is that it stays visible: `X-Capability-Defaulted` says so to the
            # caller, this says so to whoever runs the deployment, and the
            # audit log says who turned it on.
            logger.info(
                "capability_defaulted key=%s asked=%s served=%s",
                actor.display,
                capability,
                served,
            )
        # Kept for the usage row, which is the only durable record of the
        # substitution: the header is read by a client or by nobody, and the
        # log line above is gone with the container.
        requested_capability = capability if served != capability else None
        capability = served

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
        # **A bound here, the real count below.** Exact counting needs the
        # model's vocabulary, the vocabulary needs the target, and resolving
        # the target needs the routing reads that the comment on the slot
        # forbids doing first — so this is the only kind of check available
        # before a slot is held, and it is deliberately loose. It refuses
        # payloads no tokeniser could bring under the ceiling and nothing else;
        # everything between it and the ceiling waits for a slot and is then
        # judged by a figure that cannot be wrong about the model.
        #
        # This ordering is the fix for the 2026-08-17 refusal. That client's
        # payload estimated 140059 against a 122880 ceiling and was turned away
        # here, before any model was chosen; it was about 99000 real tokens,
        # and the model that would have served it could read 131072.
        floor = _floor_prompt_tokens(messages, tools)
        if floor > self._max_context_tokens:
            composition = _floor_composition(messages, tools)
            raise ContextTooLongError(
                detail=(
                    f"{_counted_phrase(COUNT_BY_LOWER_BOUND, floor)} exceeds the configured "
                    f"limit of {self._max_context_tokens}: {composition}"
                ),
                estimated=floor,
                limit=self._max_context_tokens,
                composition=composition,
                basis=COUNT_BY_LOWER_BOUND,
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

            # Inside the slot, and not by preference: counting needs `target`,
            # routing needs the reads above, and the comment at the top of this
            # block is why those reads may not happen before the slot is held.
            # So a request too long for the model that would serve it waits for
            # a slot in order to be told so — and a client retrying a permanent
            # 413 (six times in seven seconds, 2026-08-17) contends for one each
            # time. The refusal itself does no I/O and releases immediately, so
            # what it costs is the wait, not the slot; the bound above still
            # turns away the largest prompts before any of this.
            counted, basis = await self._count_prompt(target, messages, tools)
            _warn_if_tools_dominate(
                counted,
                messages,
                tools,
                self._max_context_tokens,
                self._request_id(),
                actor,
            )
            compaction_result = None
            if counted > self._max_context_tokens:
                if actor.compaction_enabled:

                    async def _recount(
                        t: Model,
                        m: Sequence[Message],
                        tl: Sequence[ToolDefinition],
                    ) -> int | None:
                        c, _ = await self._count_prompt(t, m, tl)
                        return c

                    compaction_result = await try_compact(
                        messages=messages,
                        tools=tools,
                        counted=counted,
                        limit=self._max_context_tokens,
                        count_fn=_recount,
                        target=target,
                    )
                if compaction_result is not None:
                    messages = compaction_result.messages
                    tools = compaction_result.tools
                    counted = compaction_result.tokens_after
                    logger.info(
                        "compaction applied: tier=%d %d->%d tokens, %s request_id=%s",
                        compaction_result.tier,
                        compaction_result.tokens_before,
                        compaction_result.tokens_after,
                        compaction_result.disclosure,
                        self._request_id(),
                    )
                else:
                    composition = await self._prompt_composition(target, messages, tools, basis)
                    raise ContextTooLongError(
                        detail=(
                            f"{_counted_phrase(basis, counted)} exceeds the configured limit "
                            f"of {self._max_context_tokens}: {composition}"
                        ),
                        estimated=counted,
                        limit=self._max_context_tokens,
                        composition=composition,
                        basis=basis,
                    )
            await self._refuse_what_this_target_would_truncate(
                counted, basis, target, actor, messages, tools
            )

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
                    # Carried rather than recomputed: it is one pass over the
                    # whole prompt, and the only reader is the truncation
                    # backstop, which needs the figure the guardrail judged.
                    counted,
                    basis,
                    # None on every ordinary request. Carried down because the
                    # usage row is written in `finally` here, and it is the one
                    # place the substitution outlives the request.
                    requested_capability,
                    compaction_tier=compaction_result.tier if compaction_result else None,
                    tokens_before_compaction=compaction_result.tokens_before
                    if compaction_result
                    else None,
                    tokens_after_compaction=compaction_result.tokens_after
                    if compaction_result
                    else None,
                )
            ) as generation:
                async for chunk in generation:
                    yield chunk
