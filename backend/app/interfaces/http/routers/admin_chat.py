"""The chat panel, served by the admin API rather than the public gateway.

It reuses `RouteChatRequest` unchanged and authorises by user identity instead
of an API key, so operators need not mint keys for themselves and internal
traffic is not subject to the public geo and CIDR restrictions.

**The resource guardrails still apply.** The concurrency cap, the `max_tokens`
ceiling and cancel-on-disconnect protect the hardware, not the perimeter, and
a request from the management UI can exhaust unified memory exactly as easily
as one from outside. See docs/architecture/security.md sections 4.3 and 5.2.

The request names a capability rather than a model, which is the difference
from the gateway: routing decides what serves it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.domain.entities.chat import Message, MessageRole
from app.infrastructure.di import (
    ApplyPromptTemplateFactoryDep,
    GroundChatFactoryDep,
    RouteChatRequestDep,
)
from app.interfaces.http import sse
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.chat_schemas import AdminChatRequest

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def admin_chat(
    body: AdminChatRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: RouteChatRequestDep,
    ground_chat: GroundChatFactoryDep,
    apply_template: ApplyPromptTemplateFactoryDep,
) -> StreamingResponse:
    """Always streaming. The panel has no non-streaming mode, and offering one
    would be a second path through the same use case for no caller."""
    messages = [Message(role=MessageRole(m.role), content=m.content) for m in body.messages]

    # Before grounding, so the operator's template frames everything and the
    # retrieved passages still sit beside the question they answer.
    if body.prompt_template:
        messages = await apply_template(actor.tenant_id).execute(
            actor, messages, body.prompt_template
        )

    # Grounding happens before the streaming use case rather than inside it, so
    # the retrieval read and the embedding call are not in front of the
    # concurrency slot and the `finally` that records usage. See
    # application/use_cases/ground_chat.py.
    passages: list[tuple[str, int]] = []
    if body.use_knowledge:
        messages, retrieved = await ground_chat(actor.tenant_id).execute(
            actor, messages, collection_id=body.knowledge_collection
        )
        passages = [(p.document_id, p.index) for p in retrieved]

    generation = use_case.execute(actor, body.capability, messages, body.max_tokens, body.think)

    # Priming before the response exists is what keeps authorization and
    # routing failures reportable as status codes. See interfaces/http/sse.py.
    first = await sse.prime(generation)

    return sse.streaming_response(
        completion_id=sse.new_completion_id(),
        created=sse.created_now(),
        model=body.capability,
        generation=generation,
        first=first,
        extra_headers=sse.citation_header(passages),
    )
