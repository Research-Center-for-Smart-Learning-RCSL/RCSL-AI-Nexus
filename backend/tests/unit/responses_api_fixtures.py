"""`/v1/responses`, tested against shapes a real client actually sent.

Every request body below is the one `codex-cli 0.147.0` put on the wire against
a local recorder on 2026-08-07, trimmed rather than invented. That matters more
here than usual: the endpoint exists because the runbook shipped a
configuration (`wire_api = "chat"`) that had been impossible for six months,
and the way that happened was writing to a specification instead of to a
client.
"""

from __future__ import annotations

import json

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.responses_sse import _events


async def _drain(chunks: list[CompletionChunk]) -> list[dict]:
    async def generation():  # type: ignore[no-untyped-def]
        for chunk in chunks:
            yield chunk

    events = []
    async for frame in _events(
        response_id="resp_test",
        created=0,
        model="code",
        generation=generation(),
        first=None,
    ):
        assert frame.startswith("event: "), "each frame carries an event line and a data line"
        events.append(json.loads(frame.split("data: ", 1)[1]))
    return events
