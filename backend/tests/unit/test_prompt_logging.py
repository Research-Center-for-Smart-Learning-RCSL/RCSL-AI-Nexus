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

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.read_prompt_logs import ReadPromptLogs
from app.application.use_cases.route_chat_request import RouteChatRequest
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
from app.domain.entities.prompt_log import PromptLogEntry
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import NotAuthorizedError, PromptLogNotFoundError
from app.domain.services.prompt_capture import MAX_FIELD_CHARS, TranscriptBuffer, should_capture
from app.domain.services.routing_service import RoutingService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.shared.clock import FixedClock
from tests.unit.fakes import FakeAudit

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


# --- the decision --------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (None, False),
        (NOW - timedelta(seconds=1), False),
        (NOW, False),
        (NOW + timedelta(seconds=1), True),
    ],
    ids=["never-opened", "expired", "expires-exactly-now", "open"],
)
def test_the_window_is_read_from_the_actor_and_expires_by_itself(
    window: datetime | None, expected: bool
) -> None:
    """`NOW` exactly is closed, not open. A window is an expiry rather than a
    deadline that includes its own instant, and the same `<` comparison already
    governs `debug_detail_active`; the two must not disagree about the last
    second."""
    assert should_capture(actor(window=window), NOW) is expected


# --- the write path ------------------------------------------------------


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


async def test_nothing_is_written_when_the_window_is_shut() -> None:
    """The default, and the assertion the whole section rests on.

    Every ordinary request on this platform runs with every window closed. If
    that path wrote a row, the control would be inverted — metadata by default
    would be full text by default — and no screen anywhere would look different.
    """
    transcripts = RecordingTranscripts()

    await drain(build(transcripts), SHUT)

    assert transcripts.entries == []


async def test_an_open_window_records_the_assembled_prompt_and_the_completion() -> None:
    transcripts = RecordingTranscripts()

    await drain(build(transcripts), OPEN)

    entry = transcripts.entries[0]
    assert entry.completion == "Dyma 'r ateb."
    # The system message is in the record, which is the point of capturing here
    # rather than at the router: a prompt template and any retrieved knowledge
    # passages have already been merged into the message list by this layer, so
    # the transcript shows what the model actually read.
    assert "You answer in Welsh." in entry.messages
    assert "what is the unpublished result" in entry.messages
    assert entry.capability == "chat"
    assert entry.model_alias == "primary"
    assert entry.tenant_id == "t-research"
    assert entry.finish_reason == "stop"
    assert entry.completed is True
    assert entry.truncated_fields == frozenset()


async def test_the_transcript_carries_the_request_id_the_caller_was_given() -> None:
    """The lookup the table exists to serve. A caller reports a failure by
    quoting `X-Request-Id`; without this the conversation cannot be found from
    the only handle they have."""
    transcripts = RecordingTranscripts()

    await drain(build(transcripts, request_id="req_deadbeef"), OPEN)

    assert transcripts.entries[0].request_id == "req_deadbeef"


async def test_a_client_that_disconnects_still_leaves_a_partial_transcript() -> None:
    """One of the cases somebody opens a window for. The `finally` runs on
    `GeneratorExit` exactly as it does for usage, so the answer that was cut
    off is still readable afterwards — labelled as incomplete."""
    transcripts = RecordingTranscripts()
    use_case = build(transcripts)

    async with aclosing(use_case.execute(OPEN, "chat", MESSAGES)) as stream:
        async for _ in stream:
            break  # the client goes away after the first chunk

    entry = transcripts.entries[0]
    assert entry.completion == "Dyma "
    assert entry.completed is False


async def test_a_failure_to_record_the_transcript_does_not_break_the_stream() -> None:
    """A debugging feature must not be able to take out inference. The guard is
    its own, separate from usage's, so neither can cost the other."""
    transcripts = RecordingTranscripts(fail=True)

    collected = await drain(build(transcripts), OPEN)

    assert "".join(c.delta for c in collected) == "Dyma 'r ateb."


async def test_reasoning_is_recorded_apart_from_the_answer() -> None:
    """Concatenating them would misrepresent what the caller was sent — the
    same reason `CompletionChunk` keeps the two fields apart on the wire."""
    runtime = FakeRuntime(
        [
            CompletionChunk(delta="", reasoning="Let me think.", token_count=1),
            CompletionChunk(delta="42", token_count=1),
            CompletionChunk(delta="", finish_reason="stop", token_count=0),
        ]
    )
    transcripts = RecordingTranscripts()

    await drain(build(transcripts, runtime=runtime), OPEN)

    entry = transcripts.entries[0]
    assert entry.completion == "42"
    assert entry.reasoning == "Let me think."


async def test_chunks_withheld_at_the_ceiling_are_not_in_the_transcript() -> None:
    """The transcript must agree with what the caller received.

    Past the token ceiling the generator keeps *draining* the upstream to read
    its terminal token count, but forwards nothing. Recording those drained
    chunks would produce a transcript containing text the caller never saw,
    which is worse than a short one: it explains an answer that was not given.
    """
    runtime = FakeRuntime(
        [
            CompletionChunk(delta="kept", token_count=1),
            CompletionChunk(delta="WITHHELD", token_count=1),
            CompletionChunk(delta="", finish_reason="stop", token_count=0, prompt_tokens=9),
        ]
    )
    transcripts = RecordingTranscripts()

    collected = await drain(build(transcripts, runtime=runtime, ceiling=1), OPEN)

    assert "WITHHELD" not in "".join(c.delta for c in collected)
    entry = transcripts.entries[0]
    assert entry.completion == "kept"
    assert entry.finish_reason == "length", "truncation is reported honestly in the record too"
    assert entry.completed is False


async def test_tool_calls_are_counted() -> None:
    """The failure this platform has actually seen is a model answering in
    prose where a call was expected (PROGRESS.md 2026-08-05), so "did it call
    anything at all" is the first thing an operator debugging an agent loop
    reads off the row."""
    runtime = FakeRuntime(
        [
            CompletionChunk(
                delta="",
                token_count=1,
                tool_calls=(ToolCall(id="c1", name="read_file", arguments='{"p":"a.py"}'),),
            ),
            CompletionChunk(delta="", finish_reason="tool_calls", token_count=0),
        ]
    )
    transcripts = RecordingTranscripts()

    await drain(build(transcripts, runtime=runtime), OPEN)

    assert transcripts.entries[0].tool_calls == 1


# --- the size guard ------------------------------------------------------


def test_an_oversized_field_is_cut_and_says_so() -> None:
    """Not trimmed quietly. The audit log lost whole rows to a bounded column
    for months, silently, which is why the fact of having cut travels beside
    the data instead of being appended to it — an in-band marker would be read
    as something the model wrote."""
    buffer = TranscriptBuffer()
    buffer.observe(CompletionChunk(delta="x" * (MAX_FIELD_CHARS + 500), token_count=1))

    entry = buffer.build(
        at=NOW,
        actor=OPEN,
        capability="chat",
        model_alias="primary",
        request_id=None,
        messages=(Message(role=MessageRole.USER, content="hi"),),
        finish_reason="stop",
        completed=True,
    )

    assert len(entry.completion) == MAX_FIELD_CHARS
    assert entry.truncated_fields == frozenset({"completion"})
    assert "messages" not in entry.truncated_fields, "the cap is per field, not per row"


# --- the read path -------------------------------------------------------


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


async def test_listing_requires_the_scope_and_writes_no_audit_row() -> None:
    """Listing discloses no message content, and `prompt_log.list` on every
    page refresh would be noise that describes no disclosure. The row that
    matters is written when a conversation is actually read."""
    transcripts = await _one_stored_transcript()
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    with pytest.raises(NotAuthorizedError):
        await use_case.list_page(reader(Scope.LOGS_READ))

    await use_case.list_page(reader(Scope.PROMPT_LOG_READ))
    assert trail.entries == []


async def test_reading_a_transcript_is_audited_by_id() -> None:
    """The question this control exists to make answerable. Opening a window
    has been audited since the switch shipped; who then read what it captured
    had no answer at all until now."""
    transcripts = await _one_stored_transcript()
    stored = transcripts.entries[0]
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    entry = await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), stored.id)

    assert entry.completion == "Dyma 'r ateb."
    assert ("prompt_log.read", stored.id, "success") in trail.entries


async def test_the_audit_row_carries_no_message_content() -> None:
    """The one way this feature could undo its own bound.

    `audit_log` keeps 360 days; `prompt_logs` keeps 7. A snippet copied into
    the audit detail would outlive by a year the record the retention ceiling
    exists to expire, and it would do so in a table nothing about this feature
    would ever look at again.
    """
    transcripts = await _one_stored_transcript()
    stored = transcripts.entries[0]
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), stored.id)

    detail = [row for row in trail.rows if row[1] == "prompt_log.read"][0][4]
    serialised = " ".join(f"{k}={v}" for k, v in detail.items())
    assert "unpublished result" not in serialised
    assert "Welsh" not in serialised
    assert "Dyma" not in serialised
    assert detail["capability"] == "chat"


async def test_an_unknown_transcript_is_not_found_rather_than_refused() -> None:
    """The repository is tenant-scoped, so another tenant's id resolves to
    nothing. Answering "forbidden" would confirm the row exists, which is a
    cross-tenant read of one bit — and an expired transcript, which is the
    common case at a seven-day window, is genuinely absent."""
    trail = FakeAudit()
    use_case = ReadPromptLogs(RecordingTranscripts(), RoleAuthorization(), trail)

    with pytest.raises(PromptLogNotFoundError):
        await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), "no-such-id")

    assert trail.entries == [], "a read that disclosed nothing must not claim it did"
