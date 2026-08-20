"""HTTP collection boundary."""

from __future__ import annotations

from contextlib import aclosing

from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.interfaces.http.schemas.chat_schemas import (
    ChatCompletionResponse,
    Choice,
    CompletionMessage,
    ToolCallFunction,
    ToolCallIn,
    Usage,
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
