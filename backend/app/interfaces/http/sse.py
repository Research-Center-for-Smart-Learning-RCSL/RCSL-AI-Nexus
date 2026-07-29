"""Server-sent event framing for completions.

Shared by the gateway and the admin chat panel. Both send the same OpenAI
envelope, because the frontend parses one shape and a second spelling is how
the chat panel silently displayed nothing the first time round.

Two properties are the reason this is a module rather than a helper inside one
router, and both are easy to lose when the code is duplicated:

- **The first chunk is pulled before the response exists.** Handing an
  unstarted generator to `StreamingResponse` commits 200 before authorization,
  routing and reference validation have run, so a routing failure came back as
  a successful response containing an error frame while the identical
  non-streaming request returned 503.
- **`[DONE]` means "completed normally".** Emitting it after an error frame
  tells every client that treats it as the success sentinel that a truncated
  answer was fine.

See docs/architecture/backend.md section 6.

A stream may carry one **trailer**: a final frame, emitted after the answer and
before `[DONE]`, describing something that could only be known once the whole
answer existed. The management assistant uses it for a structured proposal it
has to finish writing before it can be validated. It is an optional argument
rather than a second framing function so that there stays one implementation of
the envelope, the ordering and the sentinel — the property this module exists
for. It defaults to None, so the gateway and `/admin/chat` keep exactly the
frames they had before the assistant existed; `tests/unit/test_sse_trailer.py`
pins that a stream without one is unchanged, and that a stream that failed
carries no trailer even when it was given one.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import aclosing

from fastapi.responses import StreamingResponse

from app.domain.entities.chat import CompletionChunk
from app.domain.exceptions import DomainError

DONE_SENTINEL = "data: [DONE]\n\n"

STREAM_HEADERS = {
    # Belt and braces against an intermediary buffering the stream. nginx is
    # configured with proxy_buffering off, but a caller may sit behind
    # something else that is not.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def frame(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def new_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


async def prime(generation: AsyncGenerator[CompletionChunk, None]) -> CompletionChunk | None:
    """Pull the first chunk while a status code can still be chosen.

    Closes the generator on failure, so a routing error does not leave the
    concurrency slot held by a generator nobody will consume.
    """
    try:
        return await anext(generation)
    except StopAsyncIteration:
        return None
    except BaseException:
        await generation.aclose()
        raise


Trailer = Callable[[], Awaitable[dict[str, object] | None]]
"""Produces the optional final frame. Awaited once, after the generation has
been drained and only when it completed without error, so what it returns may
depend on the whole answer having arrived."""


def streaming_response(
    *,
    completion_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
    trailer: Trailer | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _frames(completion_id, created, model, generation, first, trailer),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


def created_now() -> int:
    return int(time.time())


async def _frames(
    completion_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
    trailer: Trailer | None = None,
) -> AsyncIterator[str]:
    def envelope(delta: dict[str, object], finish_reason: str | None) -> dict[str, object]:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    def frames_for(chunk: CompletionChunk) -> list[str]:
        out = []
        if chunk.reasoning:
            # `reasoning_content` rather than `content`, because an OpenAI
            # client must not paste a model's deliberation into the reply. It
            # is the spelling DeepSeek and vLLM already use, and a client that
            # does not know it ignores an unrecognised delta key — which is the
            # correct behaviour for one, and better than the alternative of
            # emitting nothing while the model thinks.
            out.append(frame(envelope({"reasoning_content": chunk.reasoning}, None)))
        if chunk.delta:
            out.append(frame(envelope({"content": chunk.delta}, None)))
        if chunk.finish_reason:
            out.append(frame(envelope({}, chunk.finish_reason)))
        return out

    failed = False
    yield frame(envelope({"role": "assistant"}, None))

    try:
        if first is not None:
            for f in frames_for(first):
                yield f
        # `aclosing` is the consumer's half of the streaming contract: without
        # it the use case's `finally` may not run promptly, leaking a
        # concurrency slot and leaving the runtime generating for a departed
        # client.
        async with aclosing(generation) as stream:
            async for chunk in stream:
                for f in frames_for(chunk):
                    yield f
    except DomainError as exc:
        failed = True
        # Past the first byte the status line is already committed, so this is
        # the only channel left. Inherent to SSE, documented for consumers
        # rather than worked around.
        yield frame({"error": {"code": exc.code, "message": exc.public_message}})

    if not failed:
        # Before `[DONE]`, so a client that stops reading at the sentinel — the
        # correct thing for a client to do — still receives it. After the error
        # branch, so a stream that failed carries no trailer: whatever it would
        # have described was derived from an answer that never finished.
        if trailer is not None:
            extra = await trailer()
            if extra is not None:
                yield frame(extra)
        yield DONE_SENTINEL
