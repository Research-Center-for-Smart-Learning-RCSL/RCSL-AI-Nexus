"""HTTP translation boundary."""

from __future__ import annotations

from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.interfaces.http.schemas.chat_schemas import (
    ChatCompletionRequest,
    ChatMessageIn,
    TextContentPart,
    ToolChoiceObject,
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
