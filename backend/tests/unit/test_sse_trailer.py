"""The optional final frame, and the two orderings that make it safe.

A trailer describes something only knowable once the whole answer existed — the
management assistant's proposal, which has to finish being written before it can
be validated. Adding it to the shared framing rather than writing a second
framing function is what keeps one implementation of the envelope, the error
branch and the sentinel. The cost of that choice is that the gateway now shares
a code path with a frame no OpenAI client has ever seen, so what is pinned here
is that the frame appears only when asked for, and never on a stream that failed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.domain.entities.chat import CompletionChunk
from app.domain.exceptions import NoAvailableModelError
from app.interfaces.http import sse


async def frames(
    chunks: list[CompletionChunk],
    *,
    trailer: sse.Trailer | None = None,
    fail: bool = False,
) -> list[str]:
    async def generation() -> AsyncIterator[CompletionChunk]:
        for chunk in chunks:
            yield chunk
        if fail:
            raise NoAvailableModelError(detail="gone")

    return [raw async for raw in sse._frames("id", 0, "assist", generation(), None, trailer)]


def payloads(raw: list[str]) -> list[dict]:
    return [json.loads(f.removeprefix("data: ").strip()) for f in raw if f != sse.DONE_SENTINEL]


async def constant(value: dict[str, object] | None) -> dict[str, object] | None:
    return value


# --- the gateway's shape is unchanged ------------------------------------


async def test_a_stream_with_no_trailer_carries_no_extra_frame() -> None:
    """How the gateway and `/admin/chat` call it. The argument defaults to
    None, so an OpenAI-compatible stream keeps exactly the frames it had before
    the assistant existed."""
    raw = await frames([CompletionChunk(delta="hi", finish_reason="stop")])

    assert all("proposal" not in f for f in raw)
    assert raw[-1] == sse.DONE_SENTINEL


async def test_a_trailer_returning_nothing_emits_nothing() -> None:
    """The ordinary case for the assistant: most replies answer a question and
    recommend no values at all."""
    raw = await frames(
        [CompletionChunk(delta="hi", finish_reason="stop")],
        trailer=lambda: constant(None),
    )

    assert all("proposal" not in f for f in raw)


# --- ordering ------------------------------------------------------------


async def test_the_trailer_arrives_before_the_done_sentinel() -> None:
    """A client is right to stop reading at `[DONE]`, so anything emitted after
    it is emitted to nobody."""
    raw = await frames(
        [CompletionChunk(delta="hi", finish_reason="stop")],
        trailer=lambda: constant({"proposal": {"action": "create"}}),
    )

    assert raw[-1] == sse.DONE_SENTINEL
    assert "proposal" in raw[-2]


async def test_a_failed_stream_carries_no_trailer() -> None:
    """`[DONE]` means "completed normally" and is withheld on error; the
    trailer follows the same rule for the same reason. Whatever it would have
    described was derived from an answer that never finished, and a proposal
    built from half a reply is exactly the thing that must not reach a form.
    """
    raw = await frames(
        [CompletionChunk(delta="partial")],
        trailer=lambda: constant({"proposal": {"action": "create"}}),
        fail=True,
    )

    assert all("proposal" not in f for f in raw)
    assert sse.DONE_SENTINEL not in raw
    assert "no_available_model" in raw[-1]


async def test_the_answer_still_precedes_the_trailer() -> None:
    raw = await frames(
        [
            CompletionChunk(delta="use a narrow key"),
            CompletionChunk(delta="", finish_reason="stop"),
        ],
        trailer=lambda: constant({"proposal": {"action": "create"}}),
    )
    bodies = payloads(raw)

    content = next(i for i, p in enumerate(bodies) if p.get("choices", [{}])[0].get("delta", {}))
    proposal = next(i for i, p in enumerate(bodies) if "proposal" in p)
    assert content < proposal
