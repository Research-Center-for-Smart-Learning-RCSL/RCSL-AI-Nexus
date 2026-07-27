"""SSE framing for reasoning.

A thinking model's deliberation reaches the wire on its own delta key. These
pin the two properties that matter: it must appear (an unframed reasoning
chunk is a silent stream, which is what an intermediary's idle timeout kills)
and it must never appear as `content` (an OpenAI client concatenates content
into the reply and sends it back as history).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http import sse


async def _frames(chunks: list[CompletionChunk]) -> list[dict]:
    async def generation() -> AsyncIterator[CompletionChunk]:
        for chunk in chunks[1:]:
            yield chunk

    out: list[dict] = []
    async for raw in sse._frames("id", 0, "chat", generation(), chunks[0] if chunks else None):
        if raw == sse.DONE_SENTINEL:
            continue
        out.append(json.loads(raw.removeprefix("data: ").strip()))
    return out


async def test_reasoning_is_framed_on_its_own_delta_key() -> None:
    frames = await _frames(
        [
            CompletionChunk(delta="", reasoning="thinking"),
            CompletionChunk(delta="answer"),
            CompletionChunk(delta="", finish_reason="stop"),
        ]
    )

    deltas = [f["choices"][0]["delta"] for f in frames if f.get("choices")]
    assert {"reasoning_content": "thinking"} in deltas
    assert {"content": "answer"} in deltas
    assert not any("content" in d and d.get("content") == "thinking" for d in deltas)


async def test_a_chunk_carrying_both_frames_reasoning_before_content() -> None:
    """Order matters on the wire: the deliberation precedes the answer it
    produced, and a client appending in arrival order must not interleave."""
    frames = await _frames([CompletionChunk(delta="answer", reasoning="because")])

    deltas = [f["choices"][0]["delta"] for f in frames if f.get("choices")]
    assert deltas.index({"reasoning_content": "because"}) < deltas.index({"content": "answer"})


async def test_a_purely_reasoning_stream_still_emits_frames() -> None:
    """The 2026-07-27 failure, at the framing layer: a generation that spends
    its whole budget thinking must still put bytes on the wire."""
    frames = await _frames(
        [
            CompletionChunk(delta="", reasoning="all budget spent here"),
            CompletionChunk(delta="", finish_reason="length"),
        ]
    )

    assert any(
        f.get("choices", [{}])[0].get("delta", {}).get("reasoning_content") for f in frames
    ), "no frames means no bytes, which is the silence the proxy cut at 30s"
