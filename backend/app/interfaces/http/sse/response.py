"""HTTP response boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi.responses import StreamingResponse

from app.domain.entities.chat import CompletionChunk

from .encoding import STREAM_HEADERS, Trailer
from .frames import _frames


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


def streaming_response(
    *,
    completion_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
    first: CompletionChunk | None,
    trailer: Trailer | None = None,
    extra_headers: dict[str, str] | None = None,
    include_usage: bool = False,
) -> StreamingResponse:
    """`extra_headers` carries anything that is not part of the completion.

    Retrieval citations go here rather than into a frame of their own, because
    the envelope is the OpenAI one and an extra frame shape would be a protocol
    error to every client that parses it strictly. Headers are also the only
    channel still open at this point that is not the body: they are sent before
    the first chunk, and the body is committed the moment streaming starts.

    `include_usage` is the caller's `stream_options.include_usage`, and is off
    unless asked for: the usage frame carries an empty `choices` array, which a
    client that did not request it may read as a malformed chunk.
    """
    return StreamingResponse(
        _frames(completion_id, created, model, generation, first, trailer, include_usage),
        media_type="text/event-stream",
        headers={**STREAM_HEADERS, **(extra_headers or {})},
    )
