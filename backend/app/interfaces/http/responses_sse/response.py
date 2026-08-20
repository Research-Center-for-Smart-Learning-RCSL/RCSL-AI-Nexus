"""HTTP response boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi.responses import StreamingResponse

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.sse import STREAM_HEADERS

from .events import _events


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
