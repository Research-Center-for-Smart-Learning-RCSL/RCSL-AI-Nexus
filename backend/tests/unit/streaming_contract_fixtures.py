"""The streaming lifecycle guarantees from docs/architecture/backend.md section 6.

These are the cases that are expensive to discover in production: a leaked
concurrency slot only shows up as the machine gradually refusing work, and
unbilled usage only shows up as a quota that never triggers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import aclosing
from datetime import UTC, datetime

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.usage import UsageRecord
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


def _cjk(chars: int) -> str:
    return "中" * chars


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


def _stream(use_case, messages):
    return use_case.execute(ACTOR, "chat", messages)


async def _drain(use_case, messages, **kwargs) -> None:
    async with aclosing(use_case.execute(ACTOR, "chat", messages, **kwargs)) as stream:
        async for _ in stream:
            pass
