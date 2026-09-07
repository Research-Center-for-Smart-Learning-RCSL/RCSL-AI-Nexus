"""HTTP encoding boundary."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable

from app.domain.entities.actor import Actor
from app.interfaces.http.request_context import current_compaction

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


Trailer = Callable[[], Awaitable[dict[str, object] | None]]


CITATION_HEADER = "X-Knowledge-Sources"


def citation_header(passages: list[tuple[str, int]]) -> dict[str, str]:
    if not passages:
        return {}
    return {CITATION_HEADER: ",".join(f"{doc}:{index}" for doc, index in passages)}


CAPABILITY_DEFAULTED_HEADER = "X-Capability-Defaulted"


def capability_defaulted_header(actor: Actor, requested: str) -> dict[str, str]:
    """Empty unless this key's default is about to be substituted.

    Asks `Actor.capability_for`, the same method `RouteChatRequest` routes on,
    rather than re-deriving the rule: the header exists to describe what the
    use case is about to do, and a second statement of an authorization rule is
    how the description comes to differ from the act. Called before the
    generator is primed, because headers are gone once the body starts.
    """
    served = actor.capability_for(requested)
    if served is None or served == requested:
        # None is a refusal, which this function has no part in: the use case
        # raises and the error handler writes the response.
        return {}
    return {CAPABILITY_DEFAULTED_HEADER: served}


COMPACTION_HEADER = "X-Context-Compacted"


def compaction_header() -> dict[str, str]:
    """Empty unless this request's prompt was reduced before it was served.

    The fourth header on this endpoint that announces a narrowing — beside
    `X-Capability-Defaulted`, `X-Dropped-Tools` and `X-Dropped-Input-Items` —
    and it is a header for the reason the roadmap gave when the first of them
    shipped: the envelope is OpenAI's, an extra frame shape is a protocol error
    to a strict client, and the durable evidence belongs on the usage row
    because it "has to outlive both a header the client may not read and a log
    line that rotates".

    **Read after the generator is primed**, unlike `capability_defaulted_header`
    beside it, and the difference is worth stating because the two look alike.
    That one is derivable from the actor before anything runs. This one is not
    known until the use case has counted the prompt, found it over the ceiling
    and reduced it — all of which happens inside the concurrency slot, upstream
    of the first chunk. `sse.prime` pulls that chunk while the response object
    still does not exist, so there is a window where the fact is known and the
    headers are not yet written. This function is only correct inside it.

    The value is machine-readable rather than the prose the use case logs.
    A caller reading it wants to branch on the tier; an operator wanting the
    sentence has the log line, and one wanting the numbers has the usage row.
    """
    compaction = current_compaction()
    if compaction is None:
        return {}
    return {COMPACTION_HEADER: f"tier={compaction.tier}"}


def created_now() -> int:
    return int(time.time())
