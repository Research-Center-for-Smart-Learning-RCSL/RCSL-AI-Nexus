"""HTTP encoding boundary."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable

from app.domain.entities.actor import Actor

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


def created_now() -> int:
    return int(time.time())
