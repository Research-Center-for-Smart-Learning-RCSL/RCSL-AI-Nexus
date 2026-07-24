"""The streaming lifecycle guarantees from docs/architecture/backend.md section 6.

These are the cases that are expensive to discover in production: a leaked
concurrency slot only shows up as the machine gradually refusing work, and
unbilled usage only shows up as a quota that never triggers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from datetime import UTC, datetime

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
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

    def __init__(self, chunks: int = 3, fail_at: int | None = None) -> None:
        self._chunks = chunks
        self._fail_at = fail_at
        self.cleaned_up = False

    async def generate(
        self, ref: str, messages: Sequence[Message], max_tokens: int | None = None
    ) -> AsyncIterator[CompletionChunk]:
        try:
            for i in range(self._chunks):
                if self._fail_at is not None and i == self._fail_at:
                    raise RuntimeError("upstream exploded")
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
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


class RecordingUsage:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    async def tokens_used_today(self, api_key_id: str) -> int:
        return 0


def build(runtime: FakeRuntime, limit: int = 1, ceiling: int = 1000):
    model = Model(
        id="m1",
        alias="primary",
        ref="primary:latest",
        runtime=RuntimeKind.OLLAMA,
        node_id="n1",
        state=ModelState.LOADED,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=8.0, context_length=8192),
    )
    node = Node(
        id="n1", name="n1", address="100.64.0.1", status=NodeStatus.ONLINE, total_memory_gb=64.0
    )
    usage = RecordingUsage()
    limiter = SemaphoreConcurrencyLimiter(limit)

    use_case = RouteChatRequest(
        policies=FakePolicies(
            RoutingPolicy(capability="chat", candidates=(RoutingCandidate("primary", 100),))
        ),
        models=FakeRepo([model]),
        nodes=FakeRepo([node]),
        usage=usage,
        runtimes={RuntimeKind.OLLAMA: runtime},
        routing=RoutingService(),
        concurrency=limiter,
        authz=RoleAuthorization(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        max_tokens_ceiling=ceiling,
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
