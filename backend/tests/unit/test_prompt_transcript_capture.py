from __future__ import annotations

from contextlib import aclosing
from datetime import datetime, timedelta

import pytest

from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    ToolCall,
)
from app.domain.services.prompt_capture import MAX_FIELD_CHARS, TranscriptBuffer, should_capture
from tests.unit.prompt_logging_fixtures import (
    MESSAGES,
    NOW,
    OPEN,
    SHUT,
    FakeRuntime,
    RecordingTranscripts,
    actor,
    build,
    drain,
)

pytest_plugins = ("tests.unit.prompt_logging_fixtures",)


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
