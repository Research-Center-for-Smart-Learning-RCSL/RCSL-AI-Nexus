"""OpenAI-compatible inference endpoint.

Wire framing lives in `interfaces/http/sse.py` rather than in the use case,
which is what lets one use case serve both this endpoint and the admin chat
panel. The domain emits `CompletionChunk`; turning that into `data: {...}`
frames is an interface concern. See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.infrastructure.di import (
    GroundChatFactoryDep,
    ListCapabilitiesDep,
    RouteChatRequestDep,
)
from app.interfaces.http import sse
from app.interfaces.http.middleware.api_key_auth import authenticate_api_key
from app.interfaces.http.schemas.chat_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageIn,
    Choice,
    CompletionMessage,
    ModelCard,
    ModelListResponse,
    TextContentPart,
    ToolCallFunction,
    ToolCallIn,
    ToolChoiceObject,
    Usage,
)

router = APIRouter(prefix="/v1", tags=["inference"])

ActorDep = Annotated[Actor, Depends(authenticate_api_key)]


@router.get("/models")
async def list_models(
    actor: ActorDep,
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
    """
    return ModelListResponse(
        data=[ModelCard(id=name) for name in await capabilities.execute(actor)]
    )


def _flatten(content: str | list[TextContentPart] | None) -> str:
    """Both content shapes down to the one the domain and the runtimes hold.

    Parts are joined without a separator. Inserting one would put characters
    into the prompt that the caller did not send, and a client that splits a
    sentence across two parts would find a space in the middle of a word.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content)


def _to_domain(messages: list[ChatMessageIn]) -> list[Message]:
    return [
        Message(
            role=MessageRole(m.role),
            content=_flatten(m.content),
            tool_calls=tuple(
                ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
                for c in m.tool_calls
            ),
            tool_call_id=m.tool_call_id,
            name=m.name,
        )
        for m in messages
    ]


def _tools(request: ChatCompletionRequest) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=t.function.name,
            description=t.function.description,
            parameters=t.function.parameters,
        )
        for t in request.tools
    ]


def _tool_choice(request: ChatCompletionRequest) -> ToolChoice | None:
    if request.tool_choice is None:
        return None
    if isinstance(request.tool_choice, ToolChoiceObject):
        return ToolChoice(
            mode=ToolChoiceMode.FUNCTION, function_name=request.tool_choice.function.name
        )
    return ToolChoice(mode=ToolChoiceMode(request.tool_choice))


def _sampling(request: ChatCompletionRequest) -> SamplingOptions | None:
    """None when the caller set nothing, so the adapters send no options block
    at all rather than an empty one."""
    options = SamplingOptions(
        temperature=request.temperature,
        top_p=request.top_p,
        stop=request.stop_sequences,
        seed=request.seed,
    )
    return None if options.is_empty() else options


# response_model=None: the return annotation is a union over a Pydantic body
# and a StreamingResponse, which FastAPI cannot turn into a response model. The
# annotation is for the type checker; the wire shape is built by hand.
@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    actor: ActorDep,
    use_case: RouteChatRequestDep,
    ground_chat: GroundChatFactoryDep,
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
    passages: list[tuple[str, int]] = []
    if body.use_knowledge:
        messages, retrieved = await ground_chat(actor.tenant_id).execute(
            actor, messages, collection_id=body.knowledge_collection
        )
        passages = [(p.document_id, p.index) for p in retrieved]

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
            # A header rather than a frame: the envelope is OpenAI's, and an
            # extra frame shape is a protocol error to a strict client.
            extra_headers=sse.citation_header(passages),
            include_usage=bool(body.stream_options and body.stream_options.include_usage),
        )

    # The same citations on this path as on the streaming one. `use_knowledge`
    # promises them in the header without qualifying which path, and a grounded
    # non-streaming answer whose sources were computed and then dropped is the
    # kind of gap nothing complains about.
    for name, value in sse.citation_header(passages).items():
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


async def _collect(
    completion_id: str,
    created: int,
    capability: str,
    actor: Actor,
    use_case: RouteChatRequest,
    messages: list[Message],
    max_tokens: int | None,
    thinking: bool | None,
    tools: list[ToolDefinition],
    tool_choice: ToolChoice | None,
    sampling: SamplingOptions | None,
) -> ChatCompletionResponse:
    """Non-streaming path.

    The port only offers streaming, so this consumes the same iterator to
    exhaustion. One execution path means the two cannot drift apart.
    """
    parts: list[str] = []
    reasoning: list[str] = []
    calls: list[ToolCallIn] = []
    tokens = 0
    prompt_tokens = 0
    finish_reason: str | None = None

    async with aclosing(
        use_case.execute(
            actor, capability, messages, max_tokens, thinking, tools, tool_choice, sampling
        )
    ) as stream:
        async for chunk in stream:
            parts.append(chunk.delta)
            reasoning.append(chunk.reasoning)
            calls.extend(
                ToolCallIn(
                    id=call.id,
                    function=ToolCallFunction(name=call.name, arguments=call.arguments),
                )
                for call in chunk.tool_calls
            )
            tokens += chunk.token_count
            # Assigned rather than summed: reported once, on the terminal
            # chunk, for the whole request.
            if chunk.prompt_tokens:
                prompt_tokens = chunk.prompt_tokens
            finish_reason = chunk.finish_reason or finish_reason

    text = "".join(parts)
    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=capability,
        choices=[
            Choice(
                message=CompletionMessage(
                    # Null rather than "" when the turn was only tool calls.
                    # An agent client replays this message back on the next
                    # turn, and an empty string is a claim the model answered
                    # and had nothing to say.
                    content=text if text or not calls else None,
                    tool_calls=calls or None,
                    reasoning_content="".join(reasoning) or None,
                ),
                finish_reason=finish_reason or "stop",
            )
        ],
        # `prompt_tokens` was left at the schema default of 0 until 2026-08-04,
        # so this envelope reported zero input for every request while the
        # runtime was reporting a real figure. An OpenAI client computes cost
        # from these three numbers.
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=tokens,
            total_tokens=prompt_tokens + tokens,
        ),
    )
