"""HTTP route boundary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.infrastructure.di import (
    ApplyPromptTemplateFactoryDep,
    GroundChatFactoryDep,
    RouteChatRequestDep,
)
from app.interfaces.http import responses_sse, sse
from app.interfaces.http.middleware.api_key_auth import authenticate_api_key
from app.interfaces.http.schemas.responses_schemas import (
    ResponsePayload,
    ResponsesRequest,
)

from .collection import _collect
from .tools import (
    _assert_no_server_side_tools,
    _assert_something_to_send,
    _sampling,
    _tool_choice,
    _tools,
)
from .translation import (
    DROPPED_INPUT_HEADER,
    DROPPED_TOOLS_HEADER,
    _dropped_input_items,
    _header_list,
    _to_domain,
)

router = APIRouter(prefix="/v1", tags=["inference"])


ActorDep = Annotated[Actor, Depends(authenticate_api_key)]


@router.post("/responses", response_model=None)
async def create_response(
    body: ResponsesRequest,
    actor: ActorDep,
    use_case: RouteChatRequestDep,
    ground_chat: GroundChatFactoryDep,
    apply_template: ApplyPromptTemplateFactoryDep,
    response: Response,
) -> ResponsePayload | StreamingResponse:
    _assert_no_server_side_tools(body)

    response_id = responses_sse.new_response_id()
    created = responses_sse.created_now()
    messages = _to_domain(body)
    _assert_something_to_send(messages)
    tools, dropped = _tools(body)
    tool_choice = _tool_choice(body)
    sampling = _sampling(body)

    headers = {DROPPED_TOOLS_HEADER: _header_list(dropped)} if dropped else {}
    dropped_items = _dropped_input_items(body)
    if dropped_items:
        headers[DROPPED_INPUT_HEADER] = _header_list(dropped_items)

    # The same two features the chat endpoint carries, applied in the same
    # order and for the same reasons: the operator's template is the outermost
    # frame, so retrieved passages sit next to the question rather than ahead
    # of the instructions. Declared in the request schema, so they are
    # implemented here — a field a caller can set and nothing reads is the
    # defect this repository keeps finding.
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
    headers.update(sse.citation_header(passages))
    # Last of the three, and computed before the generator is primed: once the
    # first frame is written the headers are gone, and a substitution nobody
    # was told about is the silence this key setting was allowed on condition
    # of breaking.
    headers.update(sse.capability_defaulted_header(actor, body.model))

    generation = use_case.execute(
        actor,
        body.model,
        messages,
        body.max_output_tokens,
        body.think,
        tools,
        tool_choice,
        sampling,
    )

    if body.stream:
        # Primed before the response object exists, so a routing failure is a
        # status code rather than a 200 carrying an error event. The same
        # obligation `sse.py` documents, and the same helper.
        first = await sse.prime(generation)
        return responses_sse.streaming_response(
            response_id=response_id,
            created=created,
            model=body.model,
            generation=generation,
            first=first,
            extra_headers=headers,
        )

    for name, value in headers.items():
        response.headers[name] = value
    return await _collect(response_id, created, body.model, generation)
