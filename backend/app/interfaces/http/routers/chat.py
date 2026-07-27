"""OpenAI-compatible inference endpoint.

Wire framing lives in `interfaces/http/sse.py` rather than in the use case,
which is what lets one use case serve both this endpoint and the admin chat
panel. The domain emits `CompletionChunk`; turning that into `data: {...}`
frames is an interface concern. See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor
from app.domain.entities.chat import Message, MessageRole
from app.infrastructure.di import RouteChatRequestDep
from app.interfaces.http import sse
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


# response_model=None: the return annotation is a union over a Pydantic body
# and a StreamingResponse, which FastAPI cannot turn into a response model. The
# annotation is for the type checker; the wire shape is built by hand.
@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    actor: ActorDep,
    use_case: RouteChatRequestDep,
) -> ChatCompletionResponse | StreamingResponse:
    completion_id = sse.new_completion_id()
    created = sse.created_now()
    messages = _to_domain(body)

    if body.stream:
        generation = use_case.execute(
            actor, body.model, messages, body.max_tokens, body.think
        )
        first = await sse.prime(generation)
        return sse.streaming_response(
            completion_id=completion_id,
            created=created,
            model=body.model,
            generation=generation,
            first=first,
        )

    return await _collect(
        completion_id, created, body.model, actor, use_case, messages, body.max_tokens, body.think
    )


async def _collect(
    completion_id: str,
    created: int,
    capability: str,
    actor: Actor,
    use_case: RouteChatRequest,
    messages: list[Message],
    max_tokens: int | None,
    thinking: bool | None,
) -> ChatCompletionResponse:
    """Non-streaming path.

    The port only offers streaming, so this consumes the same iterator to
    exhaustion. One execution path means the two cannot drift apart.
    """
    parts: list[str] = []
    reasoning: list[str] = []
    tokens = 0
    finish_reason: str | None = None

    async with aclosing(
        use_case.execute(actor, capability, messages, max_tokens, thinking)
    ) as stream:
        async for chunk in stream:
            parts.append(chunk.delta)
            reasoning.append(chunk.reasoning)
            tokens += chunk.token_count
            finish_reason = chunk.finish_reason or finish_reason

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=capability,
        choices=[
            Choice(
                message=CompletionMessage(
                    content="".join(parts),
                    reasoning_content="".join(reasoning) or None,
                ),
                finish_reason=finish_reason or "stop",
            )
        ],
        usage=Usage(completion_tokens=tokens, total_tokens=tokens),
    )
