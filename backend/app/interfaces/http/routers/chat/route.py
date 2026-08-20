"""HTTP route boundary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.infrastructure.di import (
    ApplyPromptTemplateFactoryDep,
    GroundChatFactoryDep,
    ListCapabilitiesDep,
    RouteChatRequestDep,
)
from app.interfaces.http import sse
from app.interfaces.http.middleware.api_key_auth import (
    authenticate_api_key,
    authenticate_api_key_without_quota,
)
from app.interfaces.http.schemas.chat_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCard,
    ModelListResponse,
)

from .collection import _collect
from .translation import _sampling, _to_domain, _tool_choice, _tools

router = APIRouter(prefix="/v1", tags=["inference"])


ActorDep = Annotated[Actor, Depends(authenticate_api_key)]


MetadataActorDep = Annotated[Actor, Depends(authenticate_api_key_without_quota)]


@router.get("/models")
async def list_models(
    actor: MetadataActorDep,
    capabilities: ListCapabilitiesDep,
) -> ModelListResponse:
    """What to put in the `model` field.

    Every OpenAI-compatible client library calls this on startup, and until it
    existed they all got a 404 from a gateway that mounts `/v1/chat/completions`
    and nothing else. It matters more here than on a conventional provider,
    because the field takes a *capability* rather than a model name — a
    convention nobody can guess and, with `/openapi.json` disabled in
    production, nothing else on the wire would have told them.

    Authenticated like any other call, so it is subject to the same key
    checks, source restriction and rate limit. An unauthenticated caller
    learning what a deployment serves is a free reconnaissance answer.

    The one check it is exempt from is the token quota, because it consumes no
    tokens; `authenticate_api_key_without_quota` says why that mattered.
    """
    return ModelListResponse(
        data=[ModelCard(id=name) for name in await capabilities.execute(actor)]
    )


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    actor: ActorDep,
    use_case: RouteChatRequestDep,
    ground_chat: GroundChatFactoryDep,
    apply_template: ApplyPromptTemplateFactoryDep,
    response: Response,
) -> ChatCompletionResponse | StreamingResponse:
    completion_id = sse.new_completion_id()
    created = sse.created_now()
    messages = _to_domain(body.messages)
    tools = _tools(body)
    tool_choice = _tool_choice(body)
    sampling = _sampling(body)

    # Opt-in, and the two fields are the only non-OpenAI ones this endpoint
    # accepts. Grounding every request would surprise an API caller who never
    # asked for it, and it costs an embedding call and a slice of the context
    # window. Grounding runs before the streaming use case, so retrieval is not
    # in front of the concurrency slot; see application/use_cases/ground_chat.py.
    # Before grounding, so the operator's template is the outermost frame and
    # retrieved passages sit next to the question rather than ahead of the
    # instructions. Both run before the streaming use case; see
    # application/use_cases/apply_prompt_template.py.
    if body.prompt_template:
        messages = await apply_template(actor.tenant_id).execute(
            actor, messages, body.prompt_template
        )

    passages: list[tuple[str, int]] = []
    if body.use_knowledge:
        messages, retrieved = await ground_chat(actor.tenant_id).execute(
            actor, messages, collection_id=body.knowledge_collection
        )
        passages = [(p.document_id, p.index) for p in retrieved]

    # Both paths carry both headers, so the two cannot answer differently about
    # the same request. `capability_defaulted_header` is empty unless this key
    # has a default and it is about to fire.
    headers = {
        **sse.citation_header(passages),
        **sse.capability_defaulted_header(actor, body.model),
    }

    if body.stream:
        generation = use_case.execute(
            actor,
            body.model,
            messages,
            body.max_tokens,
            body.think,
            tools,
            tool_choice,
            sampling,
        )
        first = await sse.prime(generation)
        return sse.streaming_response(
            completion_id=completion_id,
            created=created,
            model=body.model,
            generation=generation,
            first=first,
            # Headers rather than frames: the envelope is OpenAI's, and an
            # extra frame shape is a protocol error to a strict client.
            extra_headers=headers,
            include_usage=bool(body.stream_options and body.stream_options.include_usage),
        )

    # The same headers on this path as on the streaming one. `use_knowledge`
    # promises its citations without qualifying which path, and a grounded
    # non-streaming answer whose sources were computed and then dropped is the
    # kind of gap nothing complains about.
    for name, value in headers.items():
        response.headers[name] = value

    return await _collect(
        completion_id,
        created,
        body.model,
        actor,
        use_case,
        messages,
        body.max_tokens,
        body.think,
        tools,
        tool_choice,
        sampling,
    )
