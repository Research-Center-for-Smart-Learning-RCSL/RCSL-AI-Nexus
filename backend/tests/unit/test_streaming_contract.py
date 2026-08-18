"""The streaming lifecycle guarantees from docs/architecture/backend.md section 6.

These are the cases that are expensive to discover in production: a leaked
concurrency slot only shows up as the machine gradually refusing work, and
unbilled usage only shows up as a quota that never triggers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import aclosing
from datetime import UTC, datetime

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.route_chat_request import RouteChatRequest, _estimated_tokens
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import ContextTooLongError
from app.domain.services.routing_service import RoutingService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.shared.clock import FixedClock

ACTOR = Actor(
    id="u1",
    display="tester",
    role=Role.ADMIN,
    source="dev",
    scopes=frozenset({Scope.CHAT_USE}),
)
MESSAGES = [Message(role=MessageRole.USER, content="hello")]


class FakeRuntime:
    """Yields a fixed sequence, and records whether it was closed early."""

    def __init__(self, chunks: int = 3, fail_at: int | None = None, prompt_tokens: int = 0) -> None:
        self._chunks = chunks
        self._fail_at = fail_at
        self._prompt_tokens = prompt_tokens
        self.cleaned_up = False
        self.seen_context_length: int | None = None

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        self.seen_context_length = context_length
        try:
            for i in range(self._chunks):
                if self._fail_at is not None and i == self._fail_at:
                    raise RuntimeError("upstream exploded")
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
            if self._prompt_tokens:
                # The terminal chunk, which is the only place a real adapter
                # reports the figure.
                yield CompletionChunk(
                    delta="",
                    finish_reason="stop",
                    token_count=0,
                    prompt_tokens=self._prompt_tokens,
                )
        finally:
            # A real adapter closes its upstream HTTP stream here. Without it
            # the runtime keeps generating for a client that already left.
            self.cleaned_up = True


class FakeRepo:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def list_all(self) -> list[object]:
        return self._items


class FakePolicies:
    def __init__(self, policy: RoutingPolicy | None) -> None:
        self._policy = policy

    async def get(self, capability: str) -> RoutingPolicy | None:
        return self._policy

    async def list_all(self) -> list[RoutingPolicy]:
        """What `ListCapabilities` reads when the use case is refusing.

        `build` has wired that reader from this fake since it was written, on
        the stated ground that it would answer honestly if a test ever refused
        a capability — and nothing did, so the method it needs was missing and
        the first such test got an `AttributeError` instead of a refusal.
        """
        return [] if self._policy is None else [self._policy]


class RecordingUsage:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    async def tokens_used_today(self, api_key_id: str) -> int:
        return 0


class FakeMonotonic:
    """A controllable elapsed-time source. `advance` is what a slow runtime
    calls per chunk, so the deadline can be crossed without any real waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SlowRuntime:
    """Yields forever, moving the injected clock forward on each chunk, so a
    stream that never trips the token ceiling still trips the deadline."""

    def __init__(self, monotonic: FakeMonotonic, seconds_per_chunk: float) -> None:
        self._monotonic = monotonic
        self._seconds_per_chunk = seconds_per_chunk
        self.cleaned_up = False

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        try:
            i = 0
            while True:
                self._monotonic.advance(self._seconds_per_chunk)
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
                i += 1
        finally:
            self.cleaned_up = True


def build(
    runtime,
    limit: int = 1,
    ceiling: int = 1000,
    deadline: int = 600,
    thinking_default: bool = True,
    monotonic: Callable[[], float] | None = None,
    max_context_tokens: int = 32768,
    context_length: int = 8192,
    runtime_kind: RuntimeKind = RuntimeKind.OLLAMA,
    tokens=None,
):
    model = Model(
        id="m1",
        alias="primary",
        ref="primary:latest",
        runtime=runtime_kind,
        node_id="n1",
        state=ModelState.LOADED,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=8.0, context_length=context_length),
    )
    node = Node(
        id="n1", name="n1", address="100.64.0.1", status=NodeStatus.ONLINE, total_memory_gb=64.0
    )
    usage = RecordingUsage()
    limiter = SemaphoreConcurrencyLimiter(limit)

    policies = FakePolicies(
        RoutingPolicy(capability="chat", candidates=(RoutingCandidate("primary", 100),))
    )
    use_case = RouteChatRequest(
        policies=policies,
        # Only reached when refusing a capability the key was not issued, which
        # none of these tests do; wired from the same fake so it would answer
        # honestly if one did.
        capabilities=ListCapabilities(policies=policies, authz=RoleAuthorization()),
        models=FakeRepo([model]),
        nodes=FakeRepo([node]),
        usage=usage,
        runtimes={runtime_kind: runtime},
        routing=RoutingService(),
        concurrency=limiter,
        authz=RoleAuthorization(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        max_tokens_ceiling=ceiling,
        generation_deadline_seconds=deadline,
        thinking_default=thinking_default,
        max_context_tokens=max_context_tokens,
        tokens=tokens,
        **({"monotonic": monotonic} if monotonic is not None else {}),
    )
    return use_case, usage, limiter


async def test_full_stream_records_usage_and_releases_slot() -> None:
    runtime = FakeRuntime(chunks=3)
    use_case, usage, limiter = build(runtime)

    collected = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            collected.append(chunk.delta)

    assert len(collected) == 3
    assert limiter.available == limiter.limit, "slot must be released"
    assert usage.records[0].tokens == 3
    assert usage.records[0].completed is True


async def test_the_selected_model_s_context_length_reaches_the_runtime() -> None:
    """Routing knows which model was chosen; the runtime has to be told its size.

    `ManageModels.load` sizes the runner from the registered profile, and a
    generation that omitted the same figure would start a second runner at the
    model's own maximum — undoing the load's restraint on the first request
    rather than at load. See `middleware`-free note in PROGRESS.md 2026-08-07.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime)

    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for _ in stream:
            pass

    assert runtime.seen_context_length == 8192, "the model's registered profile, not a default"


async def test_client_disconnect_releases_slot_and_bills_partial_output() -> None:
    """Abandoning the stream after one chunk must not leak the slot.

    This is why every consumer wraps iteration in `aclosing()`: the `finally`
    inside the async generator only runs when the generator is closed.
    """
    runtime = FakeRuntime(chunks=100)
    use_case, usage, limiter = build(runtime, limit=1)

    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for _ in stream:
            break  # simulate the client going away

    assert limiter.available == limiter.limit, "slot leaked on early exit"
    assert runtime.cleaned_up is True, "adapter never closed its upstream stream"
    assert usage.records, "partial output must still be recorded"
    assert usage.records[0].completed is False
    assert usage.records[0].tokens == 1


async def test_upstream_error_still_releases_slot_and_records_usage() -> None:
    runtime = FakeRuntime(chunks=5, fail_at=2)
    use_case, usage, limiter = build(runtime)

    with pytest.raises(RuntimeError):
        async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
            async for _ in stream:
                pass

    assert limiter.available == limiter.limit
    assert usage.records[0].completed is False
    assert usage.records[0].tokens == 2


async def test_max_tokens_ceiling_is_enforced_regardless_of_runtime() -> None:
    """The cap is ours, not the caller's and not the runtime's."""
    runtime = FakeRuntime(chunks=1000)
    use_case, usage, _ = build(runtime, ceiling=5)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    content = [c for c in chunks if c.delta]
    assert len(content) == 5
    assert usage.records[0].tokens == 5

    # A generation we cut off must not be reported as one the model finished:
    # OpenAI clients branch on this field to decide whether to continue.
    assert chunks[-1].finish_reason == "length"
    assert usage.records[0].completed is False, "truncation is not completion"


class OllamaShapedRuntime:
    """The real adapter's shape, which the fake above does not have.

    `FakeRuntime` never emits a terminal chunk, so it cannot show what happens
    to the figure that only rides on one. Ollama counts each content event as a
    token and reports `prompt_eval_count` exclusively on its separate `done`
    event — so anything that stops reading before that event sees no prompt at
    all.
    """

    def __init__(self, content_chunks: int = 50, prompt_tokens: int = 500) -> None:
        self._content = content_chunks
        self._prompt_tokens = prompt_tokens
        self.cleaned_up = False

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        # Honours `max_tokens`, because Ollama does: it is passed as
        # `num_predict`, so the runtime stops on the same token the ceiling
        # trips and its terminal event is the very next one. A fake that
        # ignored it would put the terminal event fifty chunks away and model
        # a runtime this platform does not have.
        try:
            budget = self._content if max_tokens is None else min(self._content, max_tokens)
            for i in range(budget):
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
            yield CompletionChunk(
                delta="",
                finish_reason="stop",
                token_count=0,
                prompt_tokens=self._prompt_tokens,
            )
        finally:
            self.cleaned_up = True


async def test_the_token_ceiling_does_not_hide_the_prompt_from_the_quota() -> None:
    """`max_tokens: 1` in front of a context-filling prompt must still be paid for.

    This was the shape of the bypass. Prompt tokens are counted so that a
    caller cannot fill the context window free of quota — but the ceiling check
    ran first and `break` left the runtime's terminal event unread, which is
    the only place the count appears. One token of quota for a hundred thousand
    tokens of work, from the change that existed to prevent exactly that.

    The fix reads on past the ceiling without forwarding, which costs nothing:
    the runtime is told `num_predict = ceiling`, so its terminal event is the
    next one.
    """
    runtime = OllamaShapedRuntime(content_chunks=50, prompt_tokens=500)
    use_case, usage, _ = build(runtime, ceiling=1)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    record = usage.records[0]
    assert record.prompt_tokens == 500, "the prompt was read and must be charged for"
    assert record.tokens == 1, "output above the ceiling was withheld, so it is not billed"

    # Still exactly one terminal frame, and still honest about why it stopped.
    # The drained terminal chunk is not forwarded, so this has to be ours.
    terminal = [c for c in chunks if c.finish_reason]
    assert len(terminal) == 1, "a truncated stream must end once, not zero or twice"
    assert terminal[0].finish_reason == "length"


async def test_a_runtime_that_never_terminates_does_not_hold_the_request_open() -> None:
    """The drain is bounded. A runtime ignoring `num_predict` must not be able
    to keep this generator reading for as long as it feels like streaming."""
    runtime = FakeRuntime(chunks=10_000)  # no terminal chunk, ever
    use_case, usage, limiter = build(runtime, ceiling=5)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    assert len([c for c in chunks if c.delta]) == 5, "the ceiling still holds"
    assert usage.records[0].tokens == 5, "drained chunks are not billed"
    assert usage.records[0].prompt_tokens == 0, "honestly unknown rather than invented"
    assert limiter.available == limiter.limit, "slot released"
    assert runtime.cleaned_up is True


async def test_wall_clock_deadline_cuts_a_slow_stream_below_the_token_ceiling() -> None:
    """A stream that never reaches the token ceiling must still be bounded.

    Ten seconds per token against a 25s deadline and a ceiling well out of
    reach: the slot is what a slow model holds, and the deadline is the only
    guardrail that releases it, since the token ceiling never trips and the
    per-read HTTP timeout never fires while chunks keep arriving.
    """
    clock = FakeMonotonic()
    runtime = SlowRuntime(clock, seconds_per_chunk=10.0)
    use_case, usage, limiter = build(runtime, limit=1, ceiling=1000, deadline=25, monotonic=clock)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    content = [c for c in chunks if c.delta]
    # Four, not three: the clock is at 10s when the first chunk arrives, and
    # since 2026-08-05 the deadline runs from there rather than from the
    # request, so that first interval is prompt evaluation rather than
    # generation. Tokens then land at 0s, 10s and 20s into the budget, and the
    # fourth crosses 25s.
    assert len(content) == 4, "three tokens under the deadline, the fourth crosses it"
    assert chunks[-1].finish_reason == "length", "a deadline cut is not a clean stop"
    assert limiter.available == limiter.limit, "slot must be released on a deadline cut"
    assert runtime.cleaned_up is True, "adapter must close its upstream on a deadline cut"
    assert usage.records[0].completed is False, "a deadline cut is not completion"
    assert usage.records[0].tokens == 4


class SlowToStartRuntime:
    """Spends a long time before its first chunk, then answers at full speed.

    A runtime evaluating a long prompt, which is the case the deadline must not
    charge for: it sends nothing at all while it reads, so from the outside it
    is indistinguishable from a fast model that has not been asked yet.
    """

    def __init__(self, monotonic: FakeMonotonic, prompt_seconds: float, chunks: int) -> None:
        self._monotonic = monotonic
        self._prompt_seconds = prompt_seconds
        self._chunks = chunks

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        self._monotonic.advance(self._prompt_seconds)
        for i in range(self._chunks):
            yield CompletionChunk(delta=f"tok{i} ", token_count=1)
        yield CompletionChunk(delta="", finish_reason="stop", token_count=0)


async def test_reading_a_long_prompt_does_not_spend_the_generation_deadline() -> None:
    """The deadline bounds a stream that produces too slowly to finish, and
    prompt evaluation produces nothing at all.

    Measured from the request it was most of the budget at a large context:
    over 550 seconds of evaluation against a 900 second deadline on this
    hardware, so the stream was cut on its first token and reported
    `finish_reason: "length"` — telling the client the model had talked too much
    when it had not yet started. What bounds prompt evaluation is the per-read
    HTTP timeout, which is the limit designed for "no bytes for the interval".
    """
    clock = FakeMonotonic()
    runtime = SlowToStartRuntime(clock, prompt_seconds=550.0, chunks=3)
    use_case, usage, _ = build(runtime, limit=1, ceiling=1000, deadline=25, monotonic=clock)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    assert chunks[-1].finish_reason == "stop", "a long prompt is not a truncated answer"
    assert len([c for c in chunks if c.delta]) == 3, "every token the model produced"
    assert usage.records[0].completed is True
    # The whole wait is still what the caller experienced, so latency keeps
    # measuring from the request even though the deadline does not.
    assert usage.records[0].latency_ms >= 550_000


async def test_deadline_disabled_by_non_positive_value() -> None:
    """Zero disables the deadline, matching the heartbeat convention. The token
    ceiling remains the bound, so the stream stops there rather than never."""
    clock = FakeMonotonic()
    runtime = SlowRuntime(clock, seconds_per_chunk=10_000.0)
    use_case, usage, _ = build(runtime, limit=1, ceiling=4, deadline=0, monotonic=clock)

    content = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            if chunk.delta:
                content.append(chunk)

    assert len(content) == 4, "no deadline, so only the token ceiling stops it"
    assert usage.records[0].tokens == 4


class ThinkingRecordingRuntime:
    """Records what the port was asked for, so the resolution order between a
    request's preference and the deployment default can be pinned."""

    def __init__(self) -> None:
        self.seen: list[bool] = []

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        self.seen.append(thinking)
        yield CompletionChunk(delta="hi", token_count=1, finish_reason="stop")


async def _run(use_case, messages: Sequence[Message] | None = None, **kwargs) -> None:
    async with aclosing(
        use_case.execute(ACTOR, "chat", messages if messages is not None else MESSAGES, **kwargs)
    ) as stream:
        async for _ in stream:
            pass


async def test_request_thinking_preference_overrides_the_deployment_default() -> None:
    """The whole point of the per-request switch.

    It cannot be per model: the registry's unique index on (node, runtime, ref)
    forbids registering the same weights twice, and the memory budget would
    count them twice if it did not. So one loaded copy has to serve both, and
    the decision travels with the request.
    """
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=True)

    await _run(use_case, thinking=False)
    assert runtime.seen == [False], "an explicit false must reach the runtime"

    await _run(use_case, thinking=True)
    assert runtime.seen[-1] is True


async def test_omitting_the_preference_takes_the_configured_default() -> None:
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=False)

    await _run(use_case)
    assert runtime.seen == [False], "None means defer, not 'think'"

    # And the default does not override an explicit opposite.
    await _run(use_case, thinking=True)
    assert runtime.seen[-1] is True


async def test_thinking_is_not_clamped_the_way_max_tokens_is() -> None:
    """`max_tokens` is clamped because it costs hardware; asking a model not to
    deliberate asks for less work, so there is nothing to protect against and
    the caller's choice stands whatever the default says."""
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=True)

    await _run(use_case, max_tokens=10**9, thinking=False)
    assert runtime.seen == [False]


# --- The input ceiling, and what it is counted in -------------------------


def _cjk(chars: int) -> str:
    return "中" * chars


async def test_the_input_ceiling_counts_cjk_at_its_real_density() -> None:
    """The ceiling was applied as a flat four characters per token until
    2026-08-14, which is right for English prose and wrong for everything else.

    Measured against the tokenizer that day: Traditional Chinese runs at 1.38
    characters per token, so 4.0 admitted 2.9x the configured ceiling. That is
    how a Codex session was let past 65,536 tokens on a limit of 65,536 — and
    the runtime, which truncates rather than refuses, would have answered
    without the start of the conversation.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    # 1500 CJK characters is ~1360 real tokens and was ~375 under the old rule.
    with pytest.raises(ContextTooLongError):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content=_cjk(1500))])


async def test_the_input_ceiling_still_admits_the_prose_it_always_did() -> None:
    """The correction must not pay for CJK by charging English four times over:
    ASCII is weighted separately, so ordinary prose keeps roughly the capacity
    it had."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 500)])


async def test_the_refusal_names_the_unit_it_judged_in() -> None:
    """`characters exceeds the configured limit` against a limit expressed in
    tokens left the reader to guess at the factor between them, and the factor
    was the part that was wrong."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content=_cjk(4000))])

    assert "estimated tokens" in (caught.value.detail or "")
    assert "1000" in (caught.value.detail or "")


async def test_a_prompt_the_runtime_truncated_is_reported_to_the_operator(caplog) -> None:
    """The backstop for the estimate being wrong in the unsafe direction.

    Ollama evaluates at most `num_ctx / 2` and drops the rest silently, under a
    `done_reason` that a full generation also uses. Nothing downstream can tell
    the two apart, so the caller gets a fluent answer to a conversation the
    model only half read. Reaching that boundary means the estimator
    under-counted, which is an operator's problem rather than a caller's.
    """
    # The fake model's context_length is 8192, so the runtime's own cap is 4096.
    runtime = FakeRuntime(chunks=1, prompt_tokens=4096)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.WARNING):
        await _run(use_case)

    assert "prompt likely truncated" in caplog.text
    assert "num_ctx/2=4096" in caplog.text


async def test_an_ordinary_prompt_says_nothing(caplog) -> None:
    """The warning has to stay rare enough to mean something."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=4095)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.WARNING):
        await _run(use_case)

    assert "prompt likely truncated" not in caplog.text


async def test_a_prompt_the_target_would_truncate_is_refused_before_generating() -> None:
    """The global ceiling is one number; the model that serves the request has
    its own, and on 2026-08-17 the two disagreed by 24x.

    `chat` falls back to a smaller model deliberately — a smaller answer beats
    no answer for a person. An answer from a prompt the runtime silently cut in
    half is neither, so the fallback refuses at its own boundary rather than
    inheriting a ceiling sized for the model it is standing in for.
    """
    runtime = FakeRuntime(chunks=1)
    # Admitted by the deployment ceiling, far past what a 8192-token model reads.
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])

    assert "4096" in (caught.value.detail or "")


async def test_that_refusal_does_not_name_the_model_to_the_caller() -> None:
    """`NoAvailableModelError` is careful not to disclose the inventory a few
    lines above, and a refusal anyone can provoke by pasting a long file would
    otherwise enumerate it."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])

    assert "primary" not in (caught.value.detail or "")


async def test_the_target_ceiling_admits_what_the_model_can_actually_read() -> None:
    """The refusal is the model's real boundary, not a margin below it: the
    2026-08-17 incident was a request refused at 82,000 real tokens by a
    ceiling the model would have served."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    # ~1000 estimated tokens, comfortably inside num_ctx/2 = 4096.
    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 600)])


async def test_only_ollama_is_held_to_the_half_context_rule() -> None:
    """`num_ctx / 2` is Ollama's behaviour, not a property of runtimes. MLX
    serves its full registered context, so applying the rule there would refuse
    requests it would have answered whole."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime, max_context_tokens=32768, context_length=8192, runtime_kind=RuntimeKind.MLX
    )

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])


async def test_a_model_registered_before_profiles_were_required_is_not_judged() -> None:
    """The column defaults to 0, which is a row written before the profile was
    required rather than a model that can read nothing. `_set_num_ctx` declines
    to send that value for the same reason."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=0)

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])


async def test_an_estimate_that_disagrees_with_the_tokenizer_is_logged(caplog) -> None:
    """Until 2026-08-17 the estimate was visible only when it refused a request.
    An estimator wrong in the safe direction was therefore invisible, and being
    wrong in the safe direction still costs a caller the context they paid for:
    the incident that day was reconstructed by hand from `usage_records`.
    """
    runtime = FakeRuntime(chunks=1, prompt_tokens=100)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 100 actual: 2.0x, past the top of the band.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" in caplog.text
    assert "over-counting" in caplog.text


async def test_the_known_calibration_is_not_reported_as_drift(caplog) -> None:
    """The estimator runs 1.2x-1.5x high on everything this platform serves, so
    a threshold that called 1.2x a deviation would fire on every request and
    measure nothing. 2026-08-17's refusal was at 1.21x and belongs inside the
    band; what was wrong that day was the ceiling, not the calibration."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=165)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 165 actual, i.e. 1.21x.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" not in caplog.text


async def test_an_under_counting_estimate_is_named_as_such(caplog) -> None:
    """The two directions are not equally bad and the line says which it saw:
    under-counting is what precedes a silent truncation."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(runtime, context_length=8192)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 1000 actual: 0.2x, below the band.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "under-counting" in caplog.text


async def test_a_truncated_prompt_is_not_judged_for_drift(caplog) -> None:
    """`prompt_eval_count` reports what the runtime evaluated, which saturates
    at num_ctx/2. Dividing the estimate by a saturated figure reports a large
    *over*-count for a prompt the estimator in fact under-counted — inverting
    the one direction this signal exists to catch."""
    # 4096 is exactly num_ctx/2 for the 8192-token model, so this is truncated.
    runtime = FakeRuntime(chunks=1, prompt_tokens=4096)
    use_case, _, _ = build(runtime, context_length=8192, max_context_tokens=32768)

    with caplog.at_level(logging.INFO):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 600)])

    assert "prompt likely truncated" in caplog.text
    assert "outside its measured band" not in caplog.text


async def test_an_estimate_close_enough_to_the_tokenizer_says_nothing(caplog) -> None:
    """It is a heuristic on character widths and is expected to be loose. A line
    on every request would be noise, and noise is not measurement."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=200)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" not in caplog.text


async def test_the_refusal_says_which_part_of_the_prompt_was_large() -> None:
    """ "Too long" is a fact; the share is the part a caller can act on.

    The three shares have three different remedies, and on 2026-08-17 a refusal
    that carried only the total sent an operator looking at the conversation
    length when one re-read file was most of it.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(
            use_case,
            messages=[
                Message(role=MessageRole.USER, content="short"),
                Message(role=MessageRole.USER, content="word " * 2000),
            ],
        )

    detail = caught.value.detail or ""
    assert "2 messages" in detail
    assert "tool definitions" in detail
    # The one re-read file dominating the conversation is the case this exists
    # for, so the share has to be legible and not merely present.
    assert "% of the whole" in detail


async def test_the_refusal_counts_tool_definitions_as_their_own_share() -> None:
    """A client whose tool list alone fills the ceiling cannot fix it by
    starting a new conversation: the definitions are resent every turn. That is
    only visible if they are attributed separately from the messages."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content="hello")],
            tools=[
                ToolDefinition(
                    name=f"tool_{i}",
                    description="d" * 400,
                    parameters={"type": "object", "properties": {}},
                )
                for i in range(10)
            ],
        )

    assert "10 tool definitions" in (caught.value.detail or "")


def test_a_prompt_of_empty_strings_does_not_divide_by_zero() -> None:
    """The share is a percentage of the total, and a request can consist
    entirely of empty content."""
    from app.application.use_cases.route_chat_request import _estimated_composition

    described = _estimated_composition([Message(role=MessageRole.USER, content="")], [])

    assert "% of the whole" not in described


def test_the_caller_facing_message_carries_a_remedy_that_can_work() -> None:
    """The one 413 that had no remedy until 2026-08-17, on the error where
    sending less is the only thing that works. `detail` never leaves the
    process, so this string is the whole of what a caller is told."""
    message = ContextTooLongError().public_message

    assert "Retrying it unchanged cannot succeed" in message
    # "conversation", not "input", would be advice a caller whose tool
    # definitions fill the ceiling cannot act on.
    assert message.startswith("The input is longer")


async def test_a_large_tool_call_argument_counts_towards_the_largest_turn() -> None:
    """An agent writing a file puts the body in `tool_calls[].arguments` and
    leaves `content` empty. Measuring content alone reported that turn as 0% of
    a conversation it was almost all of — the share exists to name exactly that
    payload, so it has to see it."""
    from app.application.use_cases.route_chat_request import _estimated_composition

    described = _estimated_composition(
        [
            Message(role=MessageRole.USER, content="short"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=(ToolCall(id="c1", name="apply_patch", arguments="x" * 60000),),
            ),
        ],
        [],
    )

    # Content alone made this "largest turn ~2, 0% of the whole".
    assert "99% of the whole" in described


def test_the_estimator_weights_wide_characters_far_above_ascii() -> None:
    """Pinned because the failure mode is a later simplification back to one
    constant, which is what was wrong. The measured spread on 2026-08-14 was
    4.57 characters per token for English against 1.38 for Traditional Chinese,
    so the two classes cannot share a divisor and stay honest for either.
    """
    ascii_estimate = _estimated_tokens("a" * 3000)
    wide_estimate = _estimated_tokens(_cjk(3000))

    assert wide_estimate > ascii_estimate * 2.5
    # And neither may be optimistic enough to reintroduce the old rule, under
    # which 3000 characters of anything counted as 750 tokens.
    assert ascii_estimate > 750


async def test_a_client_spending_its_window_on_tool_definitions_is_told(caplog) -> None:
    """Said before the ceiling refuses, not when it does.

    On 2026-08-17 a client arrived with 286 definitions worth an estimated
    122870 tokens and could not send a four-message conversation. What made that
    diagnosable was the refusal naming the share -- and nothing had named it on
    any of the requests that succeeded first, on that client or on the two
    others connected the same week.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=4096)

    with caplog.at_level(logging.WARNING):
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content="hello")],
            tools=[
                ToolDefinition(
                    name=f"a_tool_with_a_long_enough_name_{i}",
                    description="A description of the sort a real client sends. " * 8,
                    parameters={"type": "object", "properties": {"q": {"type": "string"}}},
                )
                for i in range(12)
            ],
        )

    assert "tool definitions are" in caplog.text
    assert "resent every turn" in caplog.text


async def test_a_small_request_that_is_mostly_tools_says_nothing(caplog) -> None:
    """The share alone would fire on requests nobody needs to hear about: two
    tools and a one-word question is 90% tools and costs nothing. The absolute
    floor is what makes this a signal rather than a per-request footer."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1_000_000)

    with caplog.at_level(logging.WARNING):
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content="hi")],
            tools=[
                ToolDefinition(name="one", description="short", parameters={}),
                ToolDefinition(name="two", description="short", parameters={}),
            ],
        )

    assert "tool definitions are" not in caplog.text


# --- counting the prompt with the target's own vocabulary -----------------
#
# The ordering these pin is the whole of the 2026-08-17 fix: a bound before the
# slot that cannot over-refuse, and an exact count after it that decides.


class FakeCounter:
    """A counter with an opinion, and a record of whether it was consulted."""

    def __init__(self, total: int | None, parts: list[int] | None = None) -> None:
        self._total = total
        self._parts = parts
        self.asked: list[str] = []
        self.parts_asked = 0

    async def prepare(self, ref: str) -> bool:
        return self._total is not None

    async def count_prompt(self, ref, messages, tools) -> int | None:
        self.asked.append(ref)
        return self._total

    async def count_parts(self, ref, texts) -> list[int] | None:
        self.parts_asked += 1
        if self._parts is None:
            return None
        return [self._parts[i] if i < len(self._parts) else 0 for i in range(len(texts))]


async def test_a_payload_the_estimate_would_refuse_is_admitted_when_it_is_counted() -> None:
    """The refusal of 2026-08-17, in miniature. The estimate ran 1.41x high on
    that client's tool definitions, so a payload inside the ceiling was turned
    away by a figure nobody had checked against a tokeniser."""
    counter = FakeCounter(total=900)
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000, tokens=counter)
    # ~1333 by the character estimate, and 900 by the model that will read it.
    messages = [Message(role=MessageRole.USER, content="x" * 4000)]

    collected = [chunk async for chunk in _stream(use_case, messages)]

    assert collected, "the count admits what the estimate refused"
    assert counter.asked == ["primary:latest"], "counted against the model that would serve it"


async def test_the_bound_before_the_slot_refuses_without_asking_any_model() -> None:
    """It runs before routing, so it has no vocabulary to ask — and therefore
    refuses only what no tokeniser could bring under the ceiling."""
    counter = FakeCounter(total=1)
    use_case, _, limiter = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 80_000)])

    assert caught.value.basis == "lower_bound"
    assert "at least" in (caught.value.detail or "")
    assert counter.asked == [], "no model had been chosen yet"
    assert limiter.available == limiter.limit, "and no slot was taken to say so"


async def test_the_bound_admits_what_only_the_exact_count_can_judge() -> None:
    """A payload between the bound and the ceiling waits for a slot in order to
    be judged by a figure that cannot be wrong about the model. That wait is
    the price of the bound being loose, and it is the price that was chosen."""
    counter = FakeCounter(total=5000)
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert caught.value.basis == "tokenizer"
    assert caught.value.estimated == 5000
    assert "estimated tokens" not in (caught.value.detail or "")


async def test_a_counter_that_cannot_say_leaves_the_platform_where_it_was() -> None:
    """MLX targets, a model registered but not pulled, a host with no model
    store: the estimate answers, and the caller is told it is one."""
    counter = FakeCounter(total=None)
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 4000)])

    assert caught.value.basis == "estimate"
    assert "estimated tokens" in (caught.value.detail or "")


async def test_the_per_target_ceiling_judges_the_counted_figure_too() -> None:
    """The check that exists because Ollama truncates rather than refusing. It
    has to judge the same figure the global ceiling did, or the two disagree
    about the same payload."""
    counter = FakeCounter(total=5000)
    use_case, _, _ = build(
        FakeRuntime(chunks=1), max_context_tokens=100_000, context_length=8192, tokens=counter
    )

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="short")])

    assert caught.value.limit == 4096, "num_ctx/2, not the deployment ceiling"
    assert caught.value.basis == "tokenizer"


async def test_the_composition_is_counted_the_same_way_the_refusal_was() -> None:
    """A refusal quoting an exact total beside estimated shares invites
    arithmetic that does not work."""
    counter = FakeCounter(total=5000, parts=[4000])
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert counter.parts_asked == 1
    assert "~4000 in 1 messages" in (caught.value.composition or "")


async def test_an_exact_count_is_measured_against_the_runtime_on_every_request(
    caplog,
) -> None:
    """The only instrument that can catch a vocabulary bound to the wrong
    model: the ground truth lives in the runtime, so nothing offline can."""
    counter = FakeCounter(total=4000)
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(
        runtime, max_context_tokens=100_000, context_length=100_000, tokens=counter
    )

    with caplog.at_level(logging.INFO):
        await _drain(use_case, MESSAGES)

    assert "exact count disagrees with the runtime by +3000 tokens" in caplog.text


async def test_the_measured_residual_is_not_reported_as_a_disagreement(caplog) -> None:
    """Counted minus actual sat between +2 and +14 across every payload shape
    measured on 2026-08-17, so a window that called those news would fire on
    every request and say nothing."""
    counter = FakeCounter(total=1012)
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(
        runtime, max_context_tokens=100_000, context_length=100_000, tokens=counter
    )

    with caplog.at_level(logging.INFO):
        await _drain(use_case, MESSAGES)

    assert "disagrees with the runtime" not in caplog.text


def _stream(use_case, messages):
    return use_case.execute(ACTOR, "chat", messages)


async def _drain(use_case, messages, **kwargs) -> None:
    async with aclosing(use_case.execute(ACTOR, "chat", messages, **kwargs)) as stream:
        async for _ in stream:
            pass


async def test_the_bound_and_its_composition_are_measured_the_same_way() -> None:
    """The pre-slot refusal is the one path with no exact figure to reconcile
    against, so a headline on one basis beside shares on another is a
    contradiction a caller can do the arithmetic on: the bound divides ASCII by
    8.0 and the estimator by 3.0, which is a factor of 2.7."""
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 80_000)])

    error = caught.value
    assert error.basis == "lower_bound"
    parts = int((error.composition or "").split("~")[1].split(" ")[0])
    assert parts <= (error.estimated or 0), "the shares may not exceed the bound they explain"


async def test_a_composition_never_arrives_on_a_different_basis_from_its_total() -> None:
    """`count_prompt` declines for a payload shape the chat template refuses,
    while `count_parts` needs no template and would have answered exactly. Asked
    independently, that produced an estimated total beside tokenised shares."""

    class TemplateRefuses(FakeCounter):
        async def count_prompt(self, ref, messages, tools) -> int | None:
            return None

    counter = TemplateRefuses(total=None, parts=[7])
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert caught.value.basis == "estimate"
    assert counter.parts_asked == 0, "the parts must not be counted exactly for an estimated total"
    assert "~7 in 1 messages" not in (caught.value.composition or "")


async def test_the_tool_share_is_never_more_than_the_whole(caplog) -> None:
    """Dividing an estimated tool figure by an exact total mixes bases that
    differ by the factor this file's own tables record. For the 286-definition
    client of 2026-08-17 it would have read "tool definitions are 141% of this
    prompt", which is not a rounding error but a sentence nobody can act on."""
    tools = [
        ToolDefinition(name="read_record", description="x" * 400, parameters={"a": "b" * 400})
        for _ in range(40)
    ]
    counter = FakeCounter(total=900)
    use_case, _, _ = build(
        FakeRuntime(chunks=1), max_context_tokens=40_000, context_length=200_000, tokens=counter
    )

    with caplog.at_level(logging.WARNING):
        await _drain(use_case, [Message(role=MessageRole.USER, content="hi")], tools=tools)

    lines = [r for r in caplog.records if "tool definitions are about" in r.getMessage()]
    assert lines, "a payload that is almost entirely tool definitions should say so"
    share = float(lines[0].getMessage().split("about ")[1].split("%")[0])
    assert 0 < share <= 100
