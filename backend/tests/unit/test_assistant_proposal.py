"""The text protocol that carries a proposal out of a model.

Two halves are worth pinning and neither is obvious from reading the code.

The **stripping** half: a proposal block travels inside the answer, so the
reader has to hide it without hiding the answer, while the marker arrives split
across chunks at whatever boundary the tokeniser chose. Getting that wrong puts
`<propo` on the screen, or swallows the last words of every reply.

The **validating** half: what survives lands in a form with one click, so
anything malformed, truncated or outside what the platform would accept must
produce no card at all. The prose is delivered either way — the operator asked
a question and deserves the answer even when the machine-readable part of it
was unusable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.assistant_proposal import (
    PROPOSAL_CLOSE,
    PROPOSAL_CONTRACT,
    PROPOSAL_OPEN,
    ProposalCollector,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
SERVABLE = ["chat", "code"]


def collector(max_lifetime_days: int = 365) -> ProposalCollector:
    return ProposalCollector(
        now=NOW,
        servable_capabilities=SERVABLE,
        max_lifetime_days=max_lifetime_days,
    )


async def drain(c: ProposalCollector, pieces: list[str]) -> str:
    """Feed the collector one chunk per piece and return what stayed visible."""

    async def generation() -> AsyncIterator[CompletionChunk]:
        for piece in pieces:
            yield CompletionChunk(delta=piece)

    seen = []
    async for chunk in c.wrap(generation()):
        seen.append(chunk.delta)
    return "".join(seen)


def block(payload: dict) -> str:
    return PROPOSAL_OPEN + json.dumps(payload) + PROPOSAL_CLOSE


def valid_payload(**overrides: object) -> dict:
    payload: dict = {
        "action": "create",
        "fields": {"scopes": ["chat"], "rate_limit_rpm": 60},
        "rationale": "A narrow key for one integration.",
    }
    payload.update(overrides)
    return payload


# --- hiding the block ----------------------------------------------------


async def test_the_prose_survives_and_the_block_does_not() -> None:
    c = collector()

    visible = await drain(c, ["Use a narrow key. ", block(valid_payload())])

    assert visible == "Use a narrow key. "
    assert await c.trailer() is not None


async def test_a_marker_split_across_chunks_never_reaches_the_screen() -> None:
    """The case the holdback exists for. A tokeniser is free to end a chunk in
    the middle of `<proposal>`, and a partial marker on screen cannot be taken
    back once it has been streamed."""
    c = collector()
    pieces = ["Advice. ", "<prop", "osal>", json.dumps(valid_payload()), PROPOSAL_CLOSE]

    visible = await drain(c, pieces)

    assert visible == "Advice. "
    assert await c.trailer() is not None


async def test_an_answer_with_no_block_arrives_whole() -> None:
    """The holdback must be flushed at the end. Without it every reply that
    made no recommendation would lose its last nine characters, which is short
    enough to look like the model trailing off rather than like a bug."""
    c = collector()

    visible = await drain(c, ["A capability, ", "not a model name."])

    assert visible == "A capability, not a model name."
    assert await c.trailer() is None


async def test_the_terminal_chunk_still_carries_its_finish_reason() -> None:
    """Truncation has to stay visible. 2026-07-27 was spent restoring exactly
    this signal at the layer above, and a wrapper that dropped chunks whose
    text is held back would lose it again."""
    c = collector()

    async def generation() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="Answer")
        yield CompletionChunk(delta="", finish_reason="length")

    reasons = [chunk.finish_reason async for chunk in c.wrap(generation())]

    assert "length" in reasons


# --- validating what was found -------------------------------------------


async def test_a_valid_proposal_becomes_a_trailer_frame() -> None:
    c = collector()
    await drain(c, [block(valid_payload())])

    trailer = await c.trailer()

    assert trailer is not None
    assert trailer["proposal"]["action"] == "create"
    assert trailer["proposal"]["fields"]["scopes"] == ["chat"]


async def test_an_unterminated_block_is_discarded() -> None:
    """What a reply cut off by the token ceiling looks like. Half a proposal is
    not a proposal, and the prose still arrives."""
    c = collector()

    visible = await drain(c, ["Here: ", PROPOSAL_OPEN, '{"action":"cre'])

    assert visible == "Here: "
    assert await c.trailer() is None


async def test_a_block_that_is_not_json_is_discarded() -> None:
    c = collector()
    await drain(c, [PROPOSAL_OPEN + "rate_limit_rpm = 60" + PROPOSAL_CLOSE])

    assert await c.trailer() is None


async def test_a_capability_this_deployment_cannot_serve_is_refused() -> None:
    """`vision` is issuable in general but has no routing policy here, so a key
    naming it would be refused. Better no card than one that fails on save."""
    c = collector()
    await drain(c, [block(valid_payload(fields={"scopes": ["vision"]}))])

    assert await c.trailer() is None


async def test_an_expiry_beyond_the_maximum_lifetime_is_refused() -> None:
    c = collector(max_lifetime_days=90)
    beyond = (NOW + timedelta(days=120)).isoformat()
    await drain(c, [block(valid_payload(fields={"expires_at": beyond}))])

    assert await c.trailer() is None


async def test_an_expiry_already_past_is_refused() -> None:
    c = collector()
    past = (NOW - timedelta(days=1)).isoformat()
    await drain(c, [block(valid_payload(fields={"expires_at": past}))])

    assert await c.trailer() is None


async def test_an_expiry_inside_the_window_is_accepted() -> None:
    c = collector(max_lifetime_days=90)
    soon = (NOW + timedelta(days=30)).isoformat()
    await drain(c, [block(valid_payload(fields={"expires_at": soon}))])

    assert await c.trailer() is not None


async def test_a_zero_rate_limit_is_refused_by_the_shared_schema() -> None:
    """`UpdateApiKeyRequest` is what validates `fields`, so the bound the API
    enforces is the bound the proposal is held to, with nothing restated here.
    Zero used to be a way to issue an unmetered key through a form that reads
    as if it were tightening one."""
    c = collector()
    await drain(c, [block(valid_payload(fields={"rate_limit_rpm": 0}))])

    assert await c.trailer() is None


async def test_an_owner_cannot_be_proposed() -> None:
    """`UpdateApiKeyRequest` has no `owner_id`, so who holds a key is not
    something the assistant can suggest. That is the owner picker's decision,
    and it is gated on `api_key:write_any`."""
    c = collector()
    await drain(c, [block(valid_payload(fields={"owner_id": "someone-else"}))])

    trailer = await c.trailer()

    assert trailer is not None
    assert "owner_id" not in trailer["proposal"]["fields"]


async def test_an_update_naming_no_key_is_refused() -> None:
    c = collector()
    await drain(c, [block(valid_payload(action="update"))])

    assert await c.trailer() is None


# --- the agreement between the two halves --------------------------------


def test_the_contract_describes_the_markers_the_reader_searches_for() -> None:
    """The prompt half and the parser half are one agreement. If they drift the
    symptom is silent: a proposal that never appears, with nothing logged
    because nothing was ever found to reject."""
    assert PROPOSAL_OPEN in PROPOSAL_CONTRACT
    assert PROPOSAL_CLOSE in PROPOSAL_CONTRACT


# --- ordering on the wire ------------------------------------------------


async def test_the_holdback_is_released_before_the_terminal_chunk() -> None:
    """No content may follow the `finish_reason` frame.

    A client is right to stop reading at the terminal frame, so anything after
    it is written to nobody. Releasing the holdback in the flush *after* the
    loop meant every answer lost its last nine characters to any reader that
    did not opt into a trailer — including `readChatStream` without
    `onTrailer`. The same mistake is recorded against `RouteChatRequest` in
    docs/PROGRESS.md, 2026-07-27.
    """
    c = collector()

    async def generation() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="A narrow key is best here.")
        yield CompletionChunk(delta="", finish_reason="stop")

    seen: list[tuple[str, str | None]] = []
    async for chunk in c.wrap(generation()):
        seen.append((chunk.delta, chunk.finish_reason))

    assert "".join(delta for delta, _ in seen) == "A narrow key is best here."
    terminal = next(i for i, (_, reason) in enumerate(seen) if reason)
    assert all(not delta for delta, _ in seen[terminal + 1 :])


async def test_a_truncated_marker_at_the_end_is_not_shown_as_text() -> None:
    """The other half of releasing the holdback. Once the generation is over
    there is nothing left to disambiguate, but a tail that is a prefix of the
    marker is a block the model began and did not finish — dropping it beats
    printing `<propo` at the end of the answer."""
    c = collector()

    async def generation() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="Use a narrow key.<propo")
        yield CompletionChunk(delta="", finish_reason="length")

    visible = "".join([chunk.delta async for chunk in c.wrap(generation())])

    assert visible == "Use a narrow key."
    assert await c.trailer() is None
