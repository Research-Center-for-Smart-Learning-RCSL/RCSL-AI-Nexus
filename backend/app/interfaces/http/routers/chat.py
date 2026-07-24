"""OpenAI-compatible inference endpoint.

Wire framing lives here rather than in the use case, which is what lets one
use case serve both this endpoint and the admin chat panel. The domain emits
`CompletionChunk`; turning that into `data: {...}` frames is an interface
concern. See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
from app.domain.exceptions import DomainError
from app.infrastructure.di import RouteChatRequestDep
from app.interfaces.http.middleware.api_key_auth import authenticate_api_key
from app.interfaces.http.schemas.chat_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    CompletionMessage,
    Usage,
)

router = APIRouter(prefix="/v1", tags=["inference"])

ActorDep = Annotated[Actor, Depends(authenticate_api_key)]


def _to_domain(request: ChatCompletionRequest) -> list[Message]:
    return [Message(role=MessageRole(m.role), content=m.content) for m in request.messages]


def _frame(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    actor: ActorDep,
    use_case: RouteChatRequestDep,
):
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    messages = _to_domain(body)

    if body.stream:
        generation = use_case.execute(actor, body.model, messages, body.max_tokens)

        # Pulling the first chunk here, while we can still choose a status
        # code, is what keeps authorization, routing, and reference validation
        # reportable. Handing an unstarted generator to StreamingResponse
        # commits 200 before any of that has run, so a routing failure came
        # back as a successful response containing an error frame while the
        # identical non-streaming request returned 503.
        try:
            first: CompletionChunk | None = await anext(generation)
        except StopAsyncIteration:
            first = None
        except BaseException:
            await generation.aclose()
            raise

        return StreamingResponse(
            _stream(completion_id, created, body.model, generation, first),
            media_type="text/event-stream",
            headers={
                # Belt and braces against an intermediary buffering the stream.
                # nginx is configured with proxy_buffering off, but a caller
                # may sit behind something else that is not.
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return await _collect(
        completion_id, created, body.model, actor, use_case, messages, body.max_tokens
    )


async def _stream(
    completion_id: str,
    created: int,
    capability: str,
    generation: AsyncIterator[CompletionChunk],
    first: CompletionChunk | None,
) -> AsyncIterator[str]:
    """Frame an already-primed generation as SSE.

    Receives the generator rather than creating it, because the first chunk has
    to be pulled before the response exists. See `chat_completions`.
    """

    def envelope(delta: dict, finish_reason: str | None) -> dict:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": capability,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    def frames_for(chunk: CompletionChunk) -> list[str]:
        out = []
        if chunk.delta:
            out.append(_frame(envelope({"content": chunk.delta}, None)))
        if chunk.finish_reason:
            out.append(_frame(envelope({}, chunk.finish_reason)))
        return out

    failed = False
    yield _frame(envelope({"role": "assistant"}, None))

    try:
        if first is not None:
            for frame in frames_for(first):
                yield frame
        # `aclosing` is the caller's half of the streaming contract: without it
        # the use case's `finally` may not run promptly, leaking a concurrency
        # slot and leaving the runtime generating for a departed client.
        async with aclosing(generation) as stream:
            async for chunk in stream:
                for frame in frames_for(chunk):
                    yield frame
    except DomainError as exc:
        failed = True
        # Past the first byte the status line is already committed, so this is
        # the only channel left. Inherent to SSE, documented for consumers
        # rather than worked around.
        yield _frame({"error": {"code": exc.code, "message": exc.public_message}})

    if not failed:
        # `[DONE]` means "completed normally". Emitting it after an error frame
        # tells every client that treats it as the success sentinel that a
        # truncated response was fine.
        yield "data: [DONE]\n\n"


async def _collect(
    completion_id: str,
    created: int,
    capability: str,
    actor: Actor,
    use_case,
    messages: list[Message],
    max_tokens: int | None,
) -> ChatCompletionResponse:
    """Non-streaming path.

    The port only offers streaming, so this consumes the same iterator to
    exhaustion. One execution path means the two cannot drift apart.
    """
    parts: list[str] = []
    tokens = 0
    finish_reason: str | None = None

    async with aclosing(use_case.execute(actor, capability, messages, max_tokens)) as stream:
        async for chunk in stream:
            parts.append(chunk.delta)
            tokens += chunk.token_count
            finish_reason = chunk.finish_reason or finish_reason

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=capability,
        choices=[
            Choice(
                message=CompletionMessage(content="".join(parts)),
                finish_reason=finish_reason or "stop",
            )
        ],
        usage=Usage(completion_tokens=tokens, total_tokens=tokens),
    )
