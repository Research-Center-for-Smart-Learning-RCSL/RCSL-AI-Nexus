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
from math import ceil

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
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import (
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
from app.domain.services.prompt_capture import TranscriptBuffer, should_capture
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


ASCII_CHARS_PER_TOKEN = 3.0
WIDE_CHARS_PER_TOKEN = 1.1
"""How many characters of each kind one token is assumed to hold.

Measured against the tokenizer itself on 2026-08-14, by sending samples through
gemma4-31b-q8 and reading `prompt_eval_count`:

| content              | chars/token |
|----------------------|-------------|
| English prose        | 4.57        |
| JavaScript and HTML  | 3.59        |
| JSON tool schema     | 2.31        |
| Chinese with code    | 2.27        |
| Traditional Chinese  | 1.38        |
| Minified JavaScript  | **1.15**    |

The single figure of 4.0 this replaced was measured on none of it. It held for
English prose and under-counted everything else — a Traditional Chinese
conversation by 2.9x, which is why a Codex session on 2026-08-14 was admitted
at roughly 115,000 tokens against a ceiling of 65,536 and would have been
silently truncated by the runtime a few turns later.

**That table describes a model this deployment no longer routes to.** gemma4-31b-q8
is registered but serves no capability; `chat` and `code` both reach
qwen36-35b-a3b-q8, whose tokenizer is a different one. Re-measured against it on
2026-08-17, the same way:

| content              | chars/token | estimate runs |
|----------------------|-------------|---------------|
| English prose        | 4.40        | 1.47x high    |
| Python source        | 4.33        | 1.45x high    |
| TypeScript source    | 4.03        | 1.34x high    |
| Markdown             | 3.88        | 1.29x high    |
| JSON tool schema     | 3.67        | 1.22x high    |
| Traditional Chinese  | 1.49        | 1.36x high    |
| Minified JavaScript  | 2.72        | 0.91x         |
| base64 blob          | 1.39        | 0.46x         |
| git sha table        | 1.21        | 0.40x         |
| UUID list            | **1.02**    | **0.34x**     |

The constants are not retuned to it, and the second table is why: qwen36 is
*both* more efficient than gemma4 on everything this platform serves and more
fragmented on dense identifiers, so the gap between the honest case and the
pathological one grew rather than shrank. 3.0 cannot sit inside it. Raising it
to recover the 1.2x-1.5x over-count would deepen the 0.34x under-count, and the
under-count is the direction that ends in a silent truncation.

What the over-count costs is real and was paid twice on 2026-08-17. A Codex
session at roughly 82,000 real tokens estimated at 99,429 and was refused by a
98,304 ceiling the model would have served. And a second client that evening was
refused at 140,059 estimated, of which 122,870 was 286 tool definitions —
**measured against the tokenizer the same night, that payload was about 99,000
real tokens**, inside the 131,072 the model can now read and outside the 122,880
the estimate is judged against. The ceiling that refused it was the estimator,
not the hardware.

Two rows measured that night, on payloads shaped like the ones that were
refused rather than on clean samples of one content type:

| content                                   | chars/token | estimate runs |
|-------------------------------------------|-------------|---------------|
| OpenAI function tools, long snake_case    | 4.24        | 1.41x high    |
| Chinese runbook (CJK prose + shell + paths)| 1.71       | 1.00x         |

The second is not a correction of the Traditional Chinese row above, which was
pure prose; it is what a Chinese-speaking operator's payload actually looks like,
and the two errors happen to cancel in it. The first says the tool definitions
that fill an agent's window are over-counted like everything else, so the client
that could not send an empty conversation had more room than it was told.

The fix for the over-count is a real tokenizer, not a retuned constant — see the
table above for why no constant sits inside that gap. What is fixed already is
a ceiling that knows which model it is protecting; see
`RouteChatRequest._refuse_what_this_target_would_truncate`.

**Two characters per token is not a safe floor either, and no single number
is.** Minified JavaScript is denser than Chinese; punctuation and short
identifiers each cost a token. A constant safe for that case would price
ordinary prose at a quarter of its real capacity, so these values are chosen to
be honest for the content this platform actually serves — prose, source, and
CJK — and are knowingly optimistic for a pathological payload. What keeps that
from becoming a silent truncation is `_warn_if_prompt_was_truncated` below, not
this estimate.
"""


def _estimated_tokens(text: str) -> int:
    """Characters weighted by width, which is the cheapest signal that
    correlates with tokenizer density: scripts outside ASCII are near one token
    per character in every tokenizer this platform will meet, and ASCII is not.
    """
    ascii_chars = sum(1 for c in text if c.isascii())
    wide_chars = len(text) - ascii_chars
    return ceil(ascii_chars / ASCII_CHARS_PER_TOKEN + wide_chars / WIDE_CHARS_PER_TOKEN)


def _estimated_tool_tokens(tools: Sequence[ToolDefinition]) -> int:
    """What the client's tool list costs, on its own.

    A tool definition's `parameters` is arbitrary JSON, so it is measured by
    serialising it rather than by walking it: the length of the text the adapter
    will send is the figure that matters, and a nested schema has no other
    honest measure. The cost is one serialisation of a payload the adapter
    serialises again a few lines later, against a guardrail that runs before any
    hardware is committed.

    Separate from the total because this share behaves unlike the rest of the
    prompt: it is resent whole on every turn and does not shrink when the
    conversation is restarted, so it is the one part whose remedy is not "send
    a shorter conversation".
    """
    return sum(
        _estimated_tokens(tool.name)
        + _estimated_tokens(tool.description)
        + _estimated_tokens(json.dumps(tool.parameters))
        for tool in tools
    )


def _estimated_prompt_tokens(
    messages: Sequence[Message], tools: Sequence[ToolDefinition]
) -> tuple[int, int]:
    """Everything the model will read, as (total, tool definitions).

    The tool share is returned rather than recomputed because the guardrail
    needs the total and `_warn_if_tools_dominate` needs the part, and walking
    the tools twice on the common path is the cost this file already declined
    to pay in `_describe_prompt_composition`.
    """
    total = sum(_estimated_tokens(m.content) for m in messages)
    for message in messages:
        total += sum(
            _estimated_tokens(c.name) + _estimated_tokens(c.arguments) for c in message.tool_calls
        )
    tool_tokens = _estimated_tool_tokens(tools)
    return total + tool_tokens, tool_tokens


def _describe_prompt_composition(
    messages: Sequence[Message], tools: Sequence[ToolDefinition]
) -> str:
    """Where a refused prompt's tokens actually went.

    "Too long" is a fact about a request; this is the part a caller can act on.
    The three shares have three different remedies and nothing else distinguishes
    them: a conversation that grew is fixed by starting a new one, one enormous
    message by not reading that file into it, and tool definitions that dominate
    by trimming the client's tool list — for which starting a new conversation
    does nothing at all, since the definitions are resent every turn.

    On 2026-08-17 an agent was refused while re-reading a single large HTML file
    on every turn. The refusal said only that ~99429 exceeded 98304, so what
    reached the person driving it was a number with no subject, and the session
    was restarted several times before the file was recognised as the cause.

    Walked a second time rather than returned alongside the total, because this
    runs only on the refusal path: the guardrail admits far more requests than
    it turns away, and the common path should not pay for the rare one.
    """
    message_tokens = sum(_estimated_tokens(m.content) for m in messages)
    call_tokens = sum(
        _estimated_tokens(c.name) + _estimated_tokens(c.arguments)
        for m in messages
        for c in m.tool_calls
    )
    tool_tokens = _estimated_tool_tokens(tools)
    # Content *and* the turn's own tool calls. An agent writing a file puts the
    # body in `tool_calls[].arguments` and leaves `content` empty, so measuring
    # content alone reported "largest ~40, 0% of the whole" for a conversation
    # that was one 60000-token patch — the exact case the share exists to name.
    largest = max(
        (
            _estimated_tokens(m.content)
            + sum(_estimated_tokens(c.name) + _estimated_tokens(c.arguments) for c in m.tool_calls)
            for m in messages
        ),
        default=0,
    )
    total = message_tokens + call_tokens + tool_tokens
    # Guarded because a request can consist entirely of empty strings, and a
    # share of nothing is not a number worth printing.
    share = f", {100 * largest // total}% of the whole" if total else ""
    return (
        f"~{message_tokens} in {len(messages)} messages (largest turn ~{largest}{share}), "
        f"~{call_tokens} in prior tool calls, "
        f"~{tool_tokens} in {len(tools)} tool definitions"
    )


def _warn_if_prompt_was_truncated(
    prompt_tokens: int,
    context_length: int,
    *,
    estimated: int,
    request_id: str | None,
    actor: str,
) -> None:
    """The backstop for the estimate above being wrong in the unsafe direction.

    Ollama evaluates at most `num_ctx / 2` prompt tokens and drops the rest
    without saying so — `done_reason` is `length`, which is also what a
    generation that filled its budget reports, so nothing downstream can tell
    the two apart. The caller gets a fluent answer to a conversation whose
    beginning the model never saw, and the only thing wrong with the response
    is that it is wrong.

    `RouteChatRequest._refuse_what_this_target_would_truncate` refuses against
    this same boundary before any hardware is committed, which means reaching it
    here is not a caller's problem to solve but a signal that the estimator
    under-counted their content: the refusal judged an estimate, and this judges
    what the tokenizer actually charged. Logged rather than raised: the answer
    has already been produced and generated tokens have already been paid for,
    so refusing here would bill for work and return nothing. The request id
    makes it correlate with the caller's report, which is how the 2026-08-14
    incident was diagnosed in the first place.

    The drift line below fires far more often and refuses nothing. It exists
    because the estimate was, until 2026-08-17, visible only when it refused a
    request or when this warning fired — so an estimator that was wrong in the
    *safe* direction was invisible, and being wrong in the safe direction still
    costs a caller their context. Measuring that took reconstructing it by hand
    from `usage_records` after the fact.
    """
    if not prompt_tokens or context_length <= 0:
        # Zero means the stream never reached its terminal chunk, so there is
        # no figure to judge — not that nothing was read.
        return
    if prompt_tokens < context_length // 2:
        # Only here. Past the boundary `prompt_eval_count` reports what the
        # runtime *evaluated*, which saturates at num_ctx/2, so the ratio below
        # would divide by a number that stopped tracking the prompt: a 115000
        # prompt estimated at 100000 and cut to 4096 reads as a 24x over-count
        # when the estimator in fact under-counted. That is the one direction
        # this signal exists to catch, inverted.
        _log_estimate_drift(prompt_tokens, estimated=estimated, request_id=request_id, actor=actor)
        return
    logger.warning(
        "prompt likely truncated by the runtime: prompt_tokens=%s reached num_ctx/2=%s "
        "(estimated %s) request_id=%s actor=%s — the token estimate under-counted this "
        "content and the model did not see the whole conversation",
        prompt_tokens,
        context_length // 2,
        estimated,
        request_id,
        actor,
    )


ESTIMATE_DRIFT_BAND = (0.9, 1.5)
"""The estimate-to-actual ratios already known to be normal, which are not news.

A symmetric tolerance was the wrong shape for this. The estimator does not sit
near 1.0 and is not meant to: measured against qwen36 on 2026-08-17 it runs
1.22x to 1.47x high on every kind of content this platform serves, and 0.34x to
0.91x on dense ASCII. Any threshold tight enough to call 1.2x a deviation fires
on essentially every request, and one loose enough to stay quiet says nothing
about the direction that matters.

So the band is the measured spread, and a line is logged only outside it. Below
0.9 the estimator is under-counting by more than any sample did, which is what
precedes a silent truncation. Above 1.5 it is over-counting by more than any
sample did, which costs callers capacity they paid for.

**This would not have fired on 2026-08-17, and should not have.** That refusal
was at 1.21x — ordinary calibration, not drift. What was wrong that day was a
ceiling with no margin for a known over-count, and the fix for it is
`RouteChatRequest._refuse_what_this_target_would_truncate`, not this line. An
earlier draft of this docstring claimed the incident as its motivation while the
threshold it set would have stayed silent through it.
"""


TOOL_SHARE_WARNING = 0.5
"""When a client's tool definitions are worth warning about, as a share of the
estimate. Half, because below that the conversation is still the thing that will
reach the ceiling and the ordinary remedies apply."""


def _warn_if_tools_dominate(
    estimated: int,
    tool_tokens: int,
    tool_count: int,
    ceiling: int,
    request_id: str | None,
    actor: Actor,
) -> None:
    """Say so *before* the client hits the ceiling, not when it does.

    A tool list is fixed for a session, resent whole on every turn, and invisible
    to the person driving the agent -- so a client spending most of its window on
    tool definitions looks, from the outside, like a platform that refuses short
    conversations. On 2026-08-17 one arrived with 286 definitions worth an
    estimated 122870 tokens, more than the whole ceiling on its own, and could
    not send a four-message conversation. The refusal named the share, which is
    what solved it; nothing had named it on the many requests that succeeded
    first.

    **Both conditions, not either.** A short request can be 90% tools and cost
    nothing, so the share alone fires on requests nobody needs to hear about. The
    absolute floor is a tenth of the ceiling, which is the point at which the
    list is spending real window rather than merely most of a small request.

    This logs on every turn while the condition holds, which for an agent loop is
    every request in the task. That is deliberate: the alternative is per-process
    state to deduplicate a line that stops the moment the client is fixed, and
    the drift log above already made the same trade.
    """
    if tool_count == 0 or estimated <= 0:
        return
    share = tool_tokens / estimated
    if share < TOOL_SHARE_WARNING or tool_tokens < ceiling // 10:
        return
    logger.warning(
        "tool definitions are %.0f%% of this prompt: ~%s estimated tokens in %s definitions "
        "against a ceiling of %s, resent every turn request_id=%s actor=%s",
        share * 100,
        tool_tokens,
        tool_count,
        ceiling,
        request_id,
        actor.display,
    )


def _log_estimate_drift(
    prompt_tokens: int, *, estimated: int, request_id: str | None, actor: str
) -> None:
    """One line when the estimate leaves the spread it was measured to have.

    INFO rather than WARNING: on its own it is a calibration observation, not a
    fault, and the fault it precedes has its own warning above. The caller is
    told nothing — by the time this runs their answer has already been produced.

    Only reached for prompts the runtime read whole; see the caller for why a
    truncated one cannot be judged this way.
    """
    if not estimated:
        return
    ratio = estimated / prompt_tokens
    low, high = ESTIMATE_DRIFT_BAND
    if low <= ratio <= high:
        return
    logger.info(
        "token estimate outside its measured band: estimated=%s actual=%s ratio=%.2f "
        "(expected %.2f-%.2f) request_id=%s actor=%s — %s",
        estimated,
        prompt_tokens,
        ratio,
        low,
        high,
        request_id,
        actor,
        "under-counting, which is what precedes a silent truncation"
        if ratio < low
        else "over-counting, which refuses requests the model would have served",
    )


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
        capabilities: ListCapabilities,
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
        if not actor.may_use(capability):
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
        estimated, tool_tokens = _estimated_prompt_tokens(messages, tools)
        _warn_if_tools_dominate(
            estimated,
            tool_tokens,
            len(tools),
            self._max_context_tokens,
            self._request_id(),
            actor,
        )
        if estimated > self._max_context_tokens:
            composition = _describe_prompt_composition(messages, tools)
            raise ContextTooLongError(
                detail=(
                    f"~{estimated} estimated tokens exceeds the configured limit "
                    f"of {self._max_context_tokens}: {composition}"
                ),
                estimated=estimated,
                limit=self._max_context_tokens,
                composition=composition,
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

            # Inside the slot, and not by preference: the check needs `target`,
            # routing needs the reads above, and the comment at the top of this
            # block is why those reads may not happen before the slot is held.
            # So a request too long for the model that would serve it waits for
            # a slot in order to be told so — and a client retrying a permanent
            # 413 (six times in seven seconds, 2026-08-17) contends for one each
            # time. The refusal itself does no I/O and releases immediately, so
            # what it costs is the wait, not the slot; the global ceiling still
            # turns away the largest prompts before any of this.
            self._refuse_what_this_target_would_truncate(estimated, target, actor, messages, tools)

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
                    estimated,
                )
            ) as generation:
                async for chunk in generation:
                    yield chunk

    def _refuse_what_this_target_would_truncate(
        self,
        estimated: int,
        target: Model,
        actor: Actor,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> None:
        """The input ceiling again, against the model that will actually serve it.

        `max_context_length` is one number for the whole deployment, and its
        docstring asks an operator to keep it below half the registered
        `context_length` of *every* model that serves a capability — by hand,
        across three values that live in three different places. On 2026-08-17
        that invariant was not holding: the global ceiling was 98304 and exactly
        half of `qwen36-35b-a3b-q8`'s registered 196608, so it sat *at* the
        truncation point rather than below it, and `chat` still fell back to
        `qwen7b`, whose 8192 put the same point at 4096 — twenty-four times
        under the ceiling that admitted the request.

        **The capability it actually bit was `assist`,** which routes to
        `qwen7b` alone. The management assistant's own system prompt estimates
        3551 tokens against that 4096, so the first reply longer than roughly
        500 tokens made the second turn refuse — against a 1536-token reply
        budget. Before this check the same conversation was served from a
        prompt Ollama had cut the front off, which is where the instructions
        and the nonce-delimited data boundary live. `qwen7b` was widened to its
        native 32768 the same evening, putting that point at 16384; this check
        is what turned an invisible truncation into a visible one.

        Checked here because this is the first line where the target is known.
        A fallback to a smaller model now refuses rather than answering from a
        prompt whose beginning it never read, which is the failure the global
        ceiling exists to prevent and the one an operator cannot see: the reply
        is fluent, and only wrong.

        **Only Ollama halves.** MLX serves its full registered context (see
        `mlx_adapter.load`), so a target on any other runtime is bounded by the
        global ceiling alone rather than by a rule that does not describe it.

        A zero `context_length` is a row registered before the profile was
        required, not a model that can serve nothing; `_set_num_ctx` declines to
        send it for the same reason, and this declines to judge against it.
        """
        if target.runtime is not RuntimeKind.OLLAMA:
            return
        servable = target.resource_profile.context_length // 2
        if servable <= 0 or estimated <= servable:
            return
        # The alias is named to the operator and not to the caller. A refusal
        # that named it would disclose the model inventory to anyone who could
        # provoke one, which is the disclosure `NoAvailableModelError` is
        # careful about a few lines above.
        logger.warning(
            "refusing ~%s estimated tokens: %s would evaluate at most num_ctx/2=%s of "
            "them and drop the rest request_id=%s actor=%s",
            estimated,
            target.alias,
            servable,
            self._request_id(),
            actor.display,
        )
        composition = _describe_prompt_composition(messages, tools)
        # `limit` reaches the caller and is half this model's registered
        # context, so a fallback refusal tells them roughly how large the model
        # standing in is. Weighed and accepted on 2026-08-17 — a number they
        # cannot see is a refusal they cannot act on — and the alias still is
        # not sent. See `ContextTooLongError.__init__`.
        raise ContextTooLongError(
            detail=(
                f"~{estimated} estimated tokens exceeds the {servable} the model "
                f"serving this capability can read: {composition}"
            ),
            estimated=estimated,
            limit=servable,
            composition=composition,
        )

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
        estimated_prompt_tokens: int = 0,
    ) -> AsyncGenerator[CompletionChunk, None]:
        # The caller's request is honoured only where it is stricter than ours.
        # An unbounded generation is a hardware problem, not a client choice.
        ceiling = min(max_tokens or self._max_tokens_ceiling, self._max_tokens_ceiling)

        # Decided once, here, before the first chunk — never per chunk. A
        # window that expires mid-generation must not produce half a
        # transcript: that record is neither the full text somebody asked for
        # nor the absence §9.2 promises by default, and it would read as a
        # truncated answer rather than as an expired window.
        #
        # `None` when the window is shut, which is every ordinary request, and
        # nothing is accumulated at all in that case — not accumulated and
        # discarded. That is the difference between a disclosure control being
        # off and being on with its output thrown away.
        transcript: TranscriptBuffer | None = (
            TranscriptBuffer()
            if self._prompt_logs is not None and should_capture(actor, self._clock.now())
            else None
        )

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
        finish_reason: str | None = None
        """The reason that reached the client, for the transcript. Tracked
        rather than derived at the end because the two terminal paths below
        produce it differently: an upstream `stop` arrives on a chunk, while
        truncation synthesises `length` here."""

        started = self._monotonic()
        """When the request reached the runtime. Recorded as `latency_ms`, which
        is what the caller waited, prompt evaluation included."""

        generating_since: float | None = None
        """When the first chunk arrived, which is when the *deadline* starts.

        Not `started`. The deadline exists to bound a stream that keeps
        producing too slowly to finish, and a runtime evaluating a long prompt
        produces nothing at all while it does so — so measuring from the request
        spent the generation budget before generation began. At a large context
        that is most of the budget: prompt evaluation of a full context has been
        measured on this hardware at over 550 seconds, against a 900 second
        deadline. The stream was then cut on its first token and reported
        `finish_reason: "length"`, telling the client the model had talked too
        much when it had not yet started. What bounds prompt evaluation is the
        per-read timeout, which is the thing that was designed to: no bytes for
        the interval. See infrastructure/config.py, where the two are sized
        together.
        """

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
                    target.ref,
                    messages,
                    ceiling,
                    thinking,
                    tools,
                    tool_choice,
                    sampling,
                    # The same figure `ManageModels.load` gave the runtime, so
                    # this request reuses that runner rather than starting a
                    # second one sized to the model's own maximum.
                    target.resource_profile.context_length,
                )
            ) as upstream:
                async for chunk in upstream:
                    if generating_since is None:
                        generating_since = self._monotonic()
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
                        finish_reason = chunk.finish_reason
                    # Observed where it is forwarded, so the transcript holds
                    # exactly what the caller was sent. The drained chunks
                    # above are deliberately not observed: they were withheld
                    # at the ceiling, and a record that included them would
                    # disagree with the answer it exists to explain.
                    if transcript is not None:
                        transcript.observe(chunk)
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
                    #
                    # Measured from the first chunk, so that time spent reading
                    # the prompt is not charged against the budget for writing
                    # the answer. See `generating_since`.
                    if deadline > 0 and self._monotonic() - generating_since > deadline:
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
                finish_reason = "length"
            completed = not truncated
        finally:
            _warn_if_prompt_was_truncated(
                prompt_tokens,
                target.resource_profile.context_length,
                estimated=estimated_prompt_tokens,
                request_id=self._request_id(),
                actor=actor.display,
            )
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

            # The §9.2 transcript, in its own guard rather than sharing the one
            # above. Sharing it would make a failure to write the transcript
            # cost the usage record when the transcript is written second, and
            # the reverse when the order changed — and usage is what the quota
            # is enforced against, so it must never be the thing that a
            # debugging feature can take out.
            #
            # Reached only when the window was open at the start of the
            # generation, so an ordinary request does not enter this block at
            # all. It runs on client disconnect too, which is deliberate: a
            # conversation the caller abandoned mid-answer is one of the things
            # somebody opens a window to look at.
            if transcript is not None and self._prompt_logs is not None:
                try:
                    await self._prompt_logs.record(
                        transcript.build(
                            at=self._clock.now(),
                            actor=actor,
                            capability=capability,
                            model_alias=target.alias,
                            request_id=self._request_id(),
                            messages=tuple(messages),
                            finish_reason=finish_reason,
                            completed=completed,
                        )
                    )
                except Exception:  # noqa: BLE001
                    # Logged without any part of the transcript. The whole
                    # point of this table is that prompt text goes nowhere
                    # else, and an exception handler is the classic place for
                    # it to leak into a log with ordinary retention.
                    logger.exception(
                        "failed to record prompt transcript for actor=%s capability=%s",
                        actor.display,
                        capability,
                    )
