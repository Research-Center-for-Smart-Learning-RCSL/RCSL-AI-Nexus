from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.assistant_proposal import (
    PROPOSAL_CLOSE,
    PROPOSAL_OPEN,
)
from tests.unit.assistant_proposal_fixtures import (
    NOW,
    block,
    collector,
    drain,
    valid_payload,
)

pytest_plugins = ("tests.unit.assistant_proposal_fixtures",)


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
