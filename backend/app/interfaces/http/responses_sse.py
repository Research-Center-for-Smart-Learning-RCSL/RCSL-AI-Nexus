"""Server-sent events in the Responses API's shape.

A second framing module rather than a branch inside `sse.py`, because the two
protocols disagree about the thing `sse.py` exists to get right:

- Chat Completions ends with the literal `data: [DONE]`, and that sentinel
  means "completed normally".
- **The Responses API has no sentinel.** `response.completed` is the terminal
  event, and a stream that failed ends with `response.failed` instead. Emitting
  `[DONE]` here would be a frame no client parses; emitting `response.completed`
  after a failure would be the same lie `sse.py`'s docstring warns about, in
  the other protocol's vocabulary.

Everything else in that module's contract is kept, because it is about
streaming rather than about the envelope: the first chunk is pulled before the
response object exists (see `sse.prime`), the generator is closed with
`aclosing` so the use case's `finally` releases its concurrency slot, and an
error after the first byte becomes a terminal event rather than a status code
that can no longer be sent.

**The event set here is the one a real client was observed to need**, captured
from `codex-cli 0.147.0` against a local recorder on 2026-08-07 rather than
read from a specification. A deliberately minimal reply — `response.created`
followed by `response.completed` — was accepted, and adding the tool-call
events made the client execute the call and come back for a second turn. What
is not below is what no captured client asked for.

**Reasoning is not emitted, and that is a limitation rather than an omission.**
The Responses API carries a model's deliberation as `reasoning` items the
client replays on the next turn, and this platform's rule is that deliberation
is never replayed into a prompt (`CompletionChunk.reasoning`). Emitting the
events without the item, or the item without testing the round trip, are both
worse than not emitting them. The visible cost is silence while a thinking
model deliberates — which is why the `code` capability has `thinking=false`,
and why an agent should.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

from fastapi.responses import StreamingResponse

from app.domain.entities.chat import CompletionChunk
from app.domain.exceptions import DomainError
from app.interfaces.http.request_context import current_request_id, debug_detail_active
from app.interfaces.http.sse import STREAM_HEADERS


def new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def created_now() -> int:
    return int(time.time())


def event(name: str, payload: dict[str, object]) -> str:
    """Both the `event:` line and a `type` inside the data.

    Clients read one or the other and the API sends both; a client keyed on the
    field this omitted would see a stream of events it could not classify.
    """
    body = {"type": name, **payload}
    return f"event: {name}\ndata: {json.dumps(body, separators=(',', ':'))}\n\n"


def _message_item(item_id: str, text: str) -> dict[str, object]:
    return {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _call_item(item_id: str, call_id: str, name: str, arguments: str) -> dict[str, object]:
    return {
        "type": "function_call",
        "id": item_id,
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }


async def _events(
    *,
    response_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
) -> AsyncIterator[str]:
    sequence = 0

    def seq() -> int:
        nonlocal sequence
        sequence += 1
        return sequence - 1

    output: list[dict[str, object]] = []
    output_index = 0
    message_id: str | None = None
    message_text = ""
    completion_tokens = 0
    prompt_tokens = 0

    def base(status: str) -> dict[str, object]:
        return {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": status,
            "model": model,
        }

    def close_message(item_id: str, text: str, index: int) -> list[str]:
        """Both halves of ending a text item, in the order a client expects."""
        return [
            event(
                "response.output_text.done",
                {
                    "sequence_number": seq(),
                    "item_id": item_id,
                    "output_index": index,
                    "content_index": 0,
                    "text": text,
                },
            ),
            event(
                "response.output_item.done",
                {
                    "sequence_number": seq(),
                    "output_index": index,
                    "item": _message_item(item_id, text),
                },
            ),
        ]

    yield event(
        "response.created",
        {"sequence_number": seq(), "response": {**base("in_progress"), "output": []}},
    )

    def consume(chunk: CompletionChunk) -> list[str]:
        """Frames for one chunk. Text accumulates; a tool call is a whole item.

        A model that has decided to call something answers with the call rather
        than with prose, so the two rarely appear together — but they are
        handled independently because "rarely" is not "never", and a chunk
        carrying both must not lose either.
        """
        nonlocal message_id, message_text, output_index, completion_tokens, prompt_tokens
        completion_tokens += chunk.token_count
        # Assigned, not summed: a runtime reports it once, on the terminal
        # chunk, for the whole request.
        if chunk.prompt_tokens:
            prompt_tokens = chunk.prompt_tokens

        out: list[str] = []

        if chunk.delta:
            if message_id is None:
                message_id = f"msg_{uuid.uuid4().hex}"
                out.append(
                    event(
                        "response.output_item.added",
                        {
                            "sequence_number": seq(),
                            "output_index": output_index,
                            "item": {
                                "type": "message",
                                "id": message_id,
                                "role": "assistant",
                                "status": "in_progress",
                                "content": [],
                            },
                        },
                    )
                )
            message_text += chunk.delta
            out.append(
                event(
                    "response.output_text.delta",
                    {
                        "sequence_number": seq(),
                        "item_id": message_id,
                        "output_index": output_index,
                        "content_index": 0,
                        "delta": chunk.delta,
                    },
                )
            )

        for call in chunk.tool_calls:
            # A call closes any message in progress: items are ordered, and one
            # left open would sit around the call in the output array.
            if message_id is not None:
                out.extend(close_message(message_id, message_text, output_index))
                output.append(_message_item(message_id, message_text))
                message_id, message_text = None, ""
                output_index += 1

            item_id = f"fc_{uuid.uuid4().hex}"
            out.append(
                event(
                    "response.output_item.added",
                    {
                        "sequence_number": seq(),
                        "output_index": output_index,
                        "item": _call_item(item_id, call.id, call.name, ""),
                    },
                )
            )
            # Whole arguments in one delta. Both runtimes report a complete
            # call in a single event, and inventing fragments to imitate the
            # wire would be a shape no runtime produced; a client that
            # concatenates handles one piece correctly.
            out.append(
                event(
                    "response.function_call_arguments.delta",
                    {
                        "sequence_number": seq(),
                        "item_id": item_id,
                        "output_index": output_index,
                        "delta": call.arguments,
                    },
                )
            )
            out.append(
                event(
                    "response.function_call_arguments.done",
                    {
                        "sequence_number": seq(),
                        "item_id": item_id,
                        "output_index": output_index,
                        "arguments": call.arguments,
                    },
                )
            )
            done_item = _call_item(item_id, call.id, call.name, call.arguments)
            out.append(
                event(
                    "response.output_item.done",
                    {
                        "sequence_number": seq(),
                        "output_index": output_index,
                        "item": done_item,
                    },
                )
            )
            output.append(done_item)
            output_index += 1

        return out

    try:
        if first is not None:
            for frame in consume(first):
                yield frame
        async with aclosing(generation) as stream:
            async for chunk in stream:
                for frame in consume(chunk):
                    yield frame
    except DomainError as exc:
        # The status line was committed with the first byte, so this is the
        # only channel left. `response.failed`, never `response.completed`: a
        # client that treats the terminal event as success would otherwise
        # accept a truncated answer as a whole one.
        error: dict[str, object] = {"code": exc.code, "message": exc.public_message}
        request_id = current_request_id()
        if request_id is not None:
            error["request_id"] = request_id
        if debug_detail_active() and exc.detail:
            error["detail"] = exc.detail
        yield event(
            "response.failed",
            {
                "sequence_number": seq(),
                "response": {**base("failed"), "output": output, "error": error},
            },
        )
        return

    if message_id is not None:
        for frame in close_message(message_id, message_text, output_index):
            yield frame
        output.append(_message_item(message_id, message_text))

    yield event(
        "response.completed",
        {
            "sequence_number": seq(),
            "response": {
                **base("completed"),
                "output": output,
                "usage": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        },
    )


def streaming_response(
    *,
    response_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
    extra_headers: dict[str, str] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _events(
            response_id=response_id,
            created=created,
            model=model,
            generation=generation,
            first=first,
        ),
        media_type="text/event-stream",
        headers={**STREAM_HEADERS, **(extra_headers or {})},
    )
