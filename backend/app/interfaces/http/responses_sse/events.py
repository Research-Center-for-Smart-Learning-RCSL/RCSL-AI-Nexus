"""HTTP events boundary."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

from app.domain.entities.chat import CompletionChunk
from app.domain.exceptions import DomainError
from app.interfaces.http.request_context import current_request_id, debug_detail_active

from .encoding import _call_item, _message_item, event


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
    finish_reason: str | None = None
    """The last reason the use case reported, which decides the terminal event.

    Read here rather than ignored, which is what this module did until
    2026-08-09. `finish_reason: "length"` is how both runtimes and this
    platform's own ceiling say an answer was cut off, `/v1/chat/completions`
    forwards it, and dropping it here meant a truncated reply arrived as
    `response.completed` — the same lie the failure path above is written to
    avoid, told about the other way a stream can end badly. A real Codex
    session met it: a 32231-token prompt against a 32768-token window left 537
    tokens to answer in, the model stopped mid-sentence, and the client was
    told the reply was whole. See the runbook, section 5.1.
    """

    def base(status: str) -> dict[str, object]:
        return {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": status,
            "model": model,
        }

    def close_message(item_id: str, text: str, index: int, status: str = "completed") -> list[str]:
        """Both halves of ending a text item, in the order a client expects.

        `status` is the item's own, which is not always the response's. A
        message closed because a tool call began is complete as a message, so
        the default holds at the two call sites inside the loop; only the final
        close, below, can be the one that was cut off.
        """
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
                    "item": _message_item(item_id, text, status),
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
        nonlocal finish_reason
        completion_tokens += chunk.token_count
        # Assigned, not summed: a runtime reports it once, on the terminal
        # chunk, for the whole request.
        if chunk.prompt_tokens:
            prompt_tokens = chunk.prompt_tokens
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason

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

    # A stream that ran out of room, rather than one that finished. This
    # protocol spells that `response.incomplete`, and the distinction is the
    # whole point of reading `finish_reason`: a client that sees `completed`
    # renders half a sentence as the answer, while one that sees `incomplete`
    # can say so, or continue the turn itself. `"length"` is the only reason
    # either runtime or this platform's own ceiling produces; anything else
    # ended normally.
    truncated = finish_reason == "length"

    if message_id is not None:
        for frame in close_message(
            message_id, message_text, output_index, "incomplete" if truncated else "completed"
        ):
            yield frame
        output.append(
            _message_item(message_id, message_text, "incomplete" if truncated else "completed")
        )

    terminal: dict[str, object] = {
        **base("incomplete" if truncated else "completed"),
        "output": output,
        "usage": {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    if truncated:
        # `max_output_tokens` is this API's vocabulary for "the model was cut
        # off", and the reason clients branch on. It is the honest label even
        # when the ceiling that bound the answer was the context window rather
        # than the caller's own `max_output_tokens`: from here the two are the
        # same event, and inventing a reason outside the enumeration would
        # leave a client with a value it has no branch for.
        terminal["incomplete_details"] = {"reason": "max_output_tokens"}

    yield event(
        "response.incomplete" if truncated else "response.completed",
        {"sequence_number": seq(), "response": terminal},
    )
