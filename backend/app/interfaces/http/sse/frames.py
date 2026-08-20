"""HTTP frames boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

from app.domain.entities.chat import CompletionChunk
from app.domain.exceptions import DomainError
from app.interfaces.http.request_context import current_request_id, debug_detail_active

from .encoding import DONE_SENTINEL, Trailer, frame


async def _frames(
    completion_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
    trailer: Trailer | None = None,
    include_usage: bool = False,
) -> AsyncIterator[str]:
    def envelope(delta: dict[str, object], finish_reason: str | None) -> dict[str, object]:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    next_tool_index = 0
    """Runs across the whole stream, not per chunk.

    A client accumulates tool calls into a buffer keyed on this index, so
    restarting it on each chunk would merge two calls that arrived separately
    into one whose name and arguments are both concatenations."""

    completion_tokens = 0
    prompt_tokens = 0

    def frames_for(chunk: CompletionChunk) -> list[str]:
        nonlocal next_tool_index, completion_tokens, prompt_tokens
        completion_tokens += chunk.token_count
        # Assigned, not summed: the runtime reports it once for the whole
        # request, on the terminal chunk.
        if chunk.prompt_tokens:
            prompt_tokens = chunk.prompt_tokens

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
        if chunk.tool_calls:
            # Before the terminal frame, which the same chunk usually carries:
            # a runtime reports the call and the end of the turn in one event,
            # and a client that has already seen `finish_reason` has stopped
            # reading deltas for that choice.
            calls = []
            for call in chunk.tool_calls:
                calls.append(
                    {
                        "index": next_tool_index,
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                )
                next_tool_index += 1
            out.append(frame(envelope({"tool_calls": calls}, None)))
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
        #
        # `request_id` matters most here of anywhere: a mid-stream death has no
        # status line and no response headers left to carry it, so this frame
        # is the caller's only handle on the log line that explains what died.
        error: dict[str, object] = {"code": exc.code, "message": exc.public_message}
        request_id = current_request_id()
        if request_id is not None:
            error["request_id"] = request_id
        if debug_detail_active() and exc.detail:
            error["detail"] = exc.detail
        yield frame({"error": error})

    if not failed:
        if include_usage:
            # An empty `choices` array beside a `usage` object, which is the
            # shape OpenAI defined for this frame. After the terminal frame so
            # the answer is complete before its cost is stated, and inside the
            # success branch for the same reason the trailer is: the counts on
            # a stream that failed describe work that did not finish.
            yield frame(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                }
            )
        # Before `[DONE]`, so a client that stops reading at the sentinel — the
        # correct thing for a client to do — still receives it. After the error
        # branch, so a stream that failed carries no trailer: whatever it would
        # have described was derived from an answer that never finished.
        if trailer is not None:
            extra = await trailer()
            if extra is not None:
                yield frame(extra)
        yield DONE_SENTINEL
