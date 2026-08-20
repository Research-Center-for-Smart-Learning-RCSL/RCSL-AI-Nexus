"""Full prompt and completion logging (security.md section 9.2).

The section has described this since the first draft and nothing produced it
until 2026-08-08: the switch existed from the first migration, `identity.py`
read it, the Users and API keys screens displayed it, and the use it was
designed for — recording what the model read and wrote — was never written.

The properties worth pinning are the ones whose failure is silent. A control
that records *more* than it should looks identical to one behaving correctly
from every screen in the product; so does one that records nothing at all. Both
are asserted here directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

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
from app.domain.entities.prompt_log import PromptLogEntry
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.services.routing_service import RoutingService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.shared.clock import FixedClock

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

MESSAGES = [
    Message(role=MessageRole.SYSTEM, content="You answer in Welsh."),
    Message(role=MessageRole.USER, content="what is the unpublished result"),
]


def actor(*, window: datetime | None = None, api_key_id: str | None = None) -> Actor:
    return Actor(
        id="u1",
        display="tester",
        role=Role.ADMIN,
        source="dev",
        scopes=frozenset({Scope.CHAT_USE}),
        tenant_id="t-research",
        api_key_id=api_key_id,
        debug_logging_until=window,
    )


OPEN = actor(window=NOW + timedelta(hours=1))

SHUT = actor()


class FakeRuntime:
    def __init__(self, chunks: list[CompletionChunk] | None = None) -> None:
        self._chunks = chunks or [
            CompletionChunk(delta="Dyma ", token_count=1),
            CompletionChunk(delta="'r ateb.", token_count=1),
            CompletionChunk(delta="", finish_reason="stop", token_count=0, prompt_tokens=42),
        ]

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
        for chunk in self._chunks:
            yield chunk


class FakeRepo:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def list_all(self) -> list[object]:
        return self._items


class FakePolicies:
    async def get(self, capability: str) -> RoutingPolicy | None:
        return RoutingPolicy(capability=capability, candidates=(RoutingCandidate("primary", 100),))


class NullUsage:
    async def record(self, usage: UsageRecord) -> None:
        return None

    async def tokens_used_today(self, api_key_id: str) -> int:
        return 0


class RecordingTranscripts:
    """The write side, plus enough of the read side for the use-case tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[PromptLogEntry] = []
        self._fail = fail

    async def record(self, entry: PromptLogEntry) -> None:
        if self._fail:
            raise RuntimeError("the transcript table is on fire")
        self.entries.append(entry)

    async def get(self, entry_id: str) -> PromptLogEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    async def list_summaries(self, **kwargs: object) -> list[object]:
        return []

    async def count_entries(self, **kwargs: object) -> int:
        return len(self.entries)


def build(
    transcripts: RecordingTranscripts | None,
    runtime: FakeRuntime | None = None,
    ceiling: int = 1000,
    request_id: str | None = "req_abc123",
) -> RouteChatRequest:
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
    policies = FakePolicies()
    return RouteChatRequest(
        policies=policies,
        # Unused here: nothing in this file refuses a capability. Wired from the
        # same fake so it would answer honestly if something did.
        capabilities=ListCapabilities(policies=policies, authz=RoleAuthorization()),
        models=FakeRepo([model]),
        nodes=FakeRepo([node]),
        usage=NullUsage(),
        runtimes={RuntimeKind.OLLAMA: runtime or FakeRuntime()},
        routing=RoutingService(),
        concurrency=SemaphoreConcurrencyLimiter(1),
        authz=RoleAuthorization(),
        clock=FixedClock(NOW),
        max_tokens_ceiling=ceiling,
        prompt_logs=transcripts,
        request_id=lambda: request_id,
    )


async def drain(use_case: RouteChatRequest, who: Actor) -> list[CompletionChunk]:
    collected: list[CompletionChunk] = []
    async with aclosing(use_case.execute(who, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            collected.append(chunk)
    return collected


def reader(*scopes: Scope) -> Actor:
    return Actor(
        id="a1",
        display="admin@example.test",
        role=Role.ADMIN,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t-research",
    )


async def _one_stored_transcript() -> RecordingTranscripts:
    transcripts = RecordingTranscripts()
    await drain(build(transcripts), OPEN)
    return transcripts
