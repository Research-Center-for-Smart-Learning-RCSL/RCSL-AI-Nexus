"""`POST /v1/responses`, for agent clients that no longer speak Chat Completions.

Codex dropped `wire_api = "chat"` in February 2026 and this gateway served only
`/v1/chat/completions`, so the client the tool-calling work of 2026-08-05 was
built for could not connect to it at all. This is a **translation**, not a
second inference path: every request lands in the same `RouteChatRequest`, so
routing, quota, rate limiting, the six resource guardrails, cancellation and
usage recording are the ones already in force. Nothing here decides anything
about a model.

`/v1/chat/completions` is untouched and stays the documented interface. A
client that speaks it keeps working exactly as before.

The shapes translated below were captured from `codex-cli 0.147.0` on
2026-08-07 rather than taken from the specification; see
`schemas/responses_schemas.py` for why that distinction matters.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.domain.exceptions import RuntimeCapabilityError
from app.infrastructure.di import (
    ApplyPromptTemplateFactoryDep,
    GroundChatFactoryDep,
    RouteChatRequestDep,
)
from app.interfaces.http import responses_sse, sse
from app.interfaces.http.middleware.api_key_auth import authenticate_api_key
from app.interfaces.http.schemas.responses_schemas import (
    FunctionTool,
    InputFunctionCall,
    InputFunctionCallOutput,
    InputMessage,
    InputReasoning,
    InputTextPart,
    NamespaceTool,
    OutputFunctionCall,
    OutputMessage,
    OutputTextPart,
    ResponsePayload,
    ResponsesRequest,
    ResponseUsage,
    ToolChoiceFunction,
    WebSearchTool,
)

router = APIRouter(prefix="/v1", tags=["inference"])

ActorDep = Annotated[Actor, Depends(authenticate_api_key)]
"""The rest of the dependency aliases come from `di.py`, which `chat.py`
already imports. Re-declaring them here would be a second wiring of the same
use cases, and the two would drift."""

DROPPED_TOOLS_HEADER = "X-Dropped-Tools"
"""Tool types the model was never offered, and why an operator can find out.

Silently narrowing what a caller asked for is the failure this platform keeps
finding; a header is the one channel available before the body is committed.
"""


def _text_of(content: str | list[InputTextPart]) -> str:
    """Parts joined without a separator, as `chat.py::_flatten` does.

    Inserting one would put characters into the prompt the caller did not send,
    and a client that splits a sentence across two parts would find a space in
    the middle of a word.
    """
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content)


def _output_text(output: str | list[InputTextPart] | dict[str, object]) -> str:
    """A tool result as the string a runtime takes.

    Codex sends a plain string, including for a tool that failed. The API also
    permits parts and an object; both are rendered rather than refused, because
    a caller whose tool returned structured data has not done anything wrong
    and the alternative is a 422 in the middle of an agent's loop.
    """
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "".join(part.text for part in output)
    return json.dumps(output, ensure_ascii=False)


def _to_domain(request: ResponsesRequest) -> list[Message]:
    """`instructions` plus `input`, in that order.

    `instructions` is a top-level string in this API and becomes the system
    message, which is the one message a model treats as authoritative. It is
    placed first and once; anything the caller also sent as a `system` or
    `developer` role stays where it was in `input`, because reordering a
    caller's conversation is not translation.
    """
    messages: list[Message] = []
    if request.instructions:
        messages.append(Message(role=MessageRole.SYSTEM, content=request.instructions))

    items = (
        [InputMessage(role="user", content=request.input)]
        if isinstance(request.input, str)
        else request.input
    )

    for item in items:
        if isinstance(item, InputMessage):
            # `developer` is this API's spelling of a system-authored
            # instruction and has no counterpart in the domain, which models
            # the three roles a runtime accepts. Mapped to SYSTEM rather than
            # dropped: it carries the sandbox and permission rules an agent
            # depends on.
            role = MessageRole.SYSTEM if item.role == "developer" else MessageRole(item.role)
            messages.append(Message(role=role, content=_text_of(item.content)))
        elif isinstance(item, InputFunctionCall):
            # The model's own previous call, replayed. It belongs on an
            # assistant message with no content, which is the shape both
            # runtimes take history in.
            messages.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content="",
                    tool_calls=(
                        ToolCall(id=item.call_id, name=item.name, arguments=item.arguments),
                    ),
                )
            )
        elif isinstance(item, InputFunctionCallOutput):
            messages.append(
                Message(
                    role=MessageRole.TOOL,
                    content=_output_text(item.output),
                    tool_call_id=item.call_id,
                )
            )
        elif isinstance(item, InputReasoning):
            # Discarded. A model's deliberation is never replayed into a
            # prompt; see `CompletionChunk.reasoning`.
            continue

    return messages


def _tools(request: ResponsesRequest) -> tuple[list[ToolDefinition], list[str]]:
    """Flatten what the platform can serve, and name what it dropped.

    A `namespace` is a container of ordinary function tools — Codex sends
    `multi_agent_v1` holding five, every one executed by the *client* — so
    flattening it costs nothing and offering it costs nothing either. Dropping
    it would have removed a working capability for no reason.

    `web_search` is the one thing here the platform genuinely cannot do: it is
    server-side, and performing it would mean the gateway making outbound web
    requests, against the data plane's segmentation (security.md §6) and its
    SSRF stance (§7.2). Refused only when the client actually wants it; see
    `_assert_no_server_side_tools`.
    """
    definitions: list[ToolDefinition] = []
    dropped: list[str] = []

    def add(tool: FunctionTool) -> None:
        definitions.append(
            ToolDefinition(
                name=tool.name,
                # `description` is not optional in the domain; a tool without one
                # is offered with an empty string rather than refused.
                description=tool.description or "",
                parameters=tool.parameters,
            )
        )

    for tool in request.tools:
        if isinstance(tool, FunctionTool):
            add(tool)
        elif isinstance(tool, NamespaceTool):
            for nested in tool.tools:
                add(nested)
        elif isinstance(tool, WebSearchTool):
            dropped.append("web_search")
        else:
            dropped.append(getattr(tool, "type", "unknown"))

    return definitions, dropped


def _assert_no_server_side_tools(request: ResponsesRequest) -> None:
    """Refuse a web search that was actually asked for.

    `external_web_access: false` is the client saying the tool is off, and
    dropping something already declared disabled is equivalent to honouring it
    — which is why the default Codex configuration works here. `true` is a
    request for a capability this deployment does not have, and serving it
    silently would leave a model believing it can search while it never does.
    That is the failure `MLX_TOOL_CALLING_VERIFIED` exists to prevent, and the
    reason to fail at the moment the switch is turned on rather than three
    hours into a task.
    """
    for tool in request.tools:
        if isinstance(tool, WebSearchTool) and tool.external_web_access:
            raise RuntimeCapabilityError(
                detail="web_search with external_web_access is not served by this deployment"
            )


def _tool_choice(request: ResponsesRequest) -> ToolChoice | None:
    if request.tool_choice is None:
        return None
    if isinstance(request.tool_choice, ToolChoiceFunction):
        return ToolChoice(mode=ToolChoiceMode.FUNCTION, function_name=request.tool_choice.name)
    return ToolChoice(mode=ToolChoiceMode(request.tool_choice))


def _sampling(request: ResponsesRequest) -> SamplingOptions | None:
    options = SamplingOptions(temperature=request.temperature, top_p=request.top_p)
    return None if options.is_empty() else options


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
    tools, dropped = _tools(body)
    tool_choice = _tool_choice(body)
    sampling = _sampling(body)

    headers = {DROPPED_TOOLS_HEADER: ",".join(dropped)} if dropped else {}

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


async def _collect(
    response_id: str,
    created: int,
    model: str,
    generation: AsyncGenerator[CompletionChunk, None],
) -> ResponsePayload:
    """The non-streaming body, assembled from the same chunks.

    Codex always streams, so this path has no captured client behind it. It
    exists because the endpoint is public and a caller that sends
    `stream: false` must get an answer rather than a shape nobody wrote.
    """
    text = ""
    calls: list[ToolCall] = []
    output_tokens = 0
    input_tokens = 0

    async with aclosing(generation) as stream:
        async for chunk in stream:
            text += chunk.delta
            calls.extend(chunk.tool_calls)
            output_tokens += chunk.token_count
            if chunk.prompt_tokens:
                input_tokens = chunk.prompt_tokens

    output: list[OutputMessage | OutputFunctionCall] = []
    if text:
        output.append(
            OutputMessage(
                id=f"msg_{response_id[5:]}",
                content=[OutputTextPart(text=text)],
            )
        )
    for index, call in enumerate(calls):
        output.append(
            OutputFunctionCall(
                id=f"fc_{response_id[5:]}_{index}",
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
            )
        )

    return ResponsePayload(
        id=response_id,
        created_at=created,
        status="completed",
        model=model,
        output=output,
        usage=ResponseUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )
