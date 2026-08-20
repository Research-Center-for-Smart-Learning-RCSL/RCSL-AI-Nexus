"""Tool calling, end to end through each layer that touches it.

The agent loop this exists for is a round trip: the model asks for a call, the
*client* runs it, and the result comes back as a message the model has to be
able to pair with its own request. Every property pinned here is one where a
break is silent — the request still succeeds, the model just answers the wrong
conversation, or answers with prose where the caller's parser expects a call.

See docs/architecture/backend.md section 6 and docs/PROGRESS.md 2026-08-05.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import aclosing

import httpx
import pytest

from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    ToolDefinition,
)
from app.interfaces.http import sse

MESSAGES = [Message(role=MessageRole.USER, content="what is the weather")]

WEATHER = ToolDefinition(
    name="get_weather",
    description="Look up the weather",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
)


def ndjson(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def sse_lines(*events: dict) -> bytes:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return (body + "data: [DONE]\n\n").encode()


@pytest.fixture
def patch_httpx(monkeypatch):
    """Captures the outgoing request as well as replaying a response, because
    half of what matters here is what reaches the runtime."""
    sent: list[dict] = []

    def apply(handler):
        def recording(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return handler(request)

        transport = httpx.MockTransport(recording)
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)
        return sent

    return apply


async def drain(generator) -> list[CompletionChunk]:
    chunks = []
    async with aclosing(generator) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return chunks


async def frames_for(chunks: list[CompletionChunk], **kwargs) -> list[dict]:
    async def generation() -> AsyncIterator[CompletionChunk]:
        for chunk in chunks[1:]:
            yield chunk

    out: list[dict] = []
    async for raw in sse._frames("id", 0, "code", generation(), chunks[0], **kwargs):
        if raw == sse.DONE_SENTINEL:
            continue
        out.append(json.loads(raw.removeprefix("data: ").strip()))
    return out
