"""HTTP collection boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing

from app.domain.entities.chat import (
    CompletionChunk,
    ToolCall,
)
from app.interfaces.http.schemas.responses_schemas import (
    OutputFunctionCall,
    OutputMessage,
    OutputTextPart,
    ResponsePayload,
    ResponseUsage,
)


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
    finish_reason: str | None = None

    async with aclosing(generation) as stream:
        async for chunk in stream:
            text += chunk.delta
            calls.extend(chunk.tool_calls)
            output_tokens += chunk.token_count
            if chunk.prompt_tokens:
                input_tokens = chunk.prompt_tokens
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason

    # The same correction the streaming path carries, for the same reason: this
    # function hardcoded `status="completed"`, so a reply cut off at the
    # context window came back declared whole. See `responses_sse` for why
    # `"length"` is the only reason that means truncation.
    truncated = finish_reason == "length"

    output: list[OutputMessage | OutputFunctionCall] = []
    if text:
        output.append(
            OutputMessage(
                id=f"msg_{response_id[5:]}",
                status="incomplete" if truncated else "completed",
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
        status="incomplete" if truncated else "completed",
        model=model,
        output=output,
        usage=ResponseUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        incomplete_details={"reason": "max_output_tokens"} if truncated else None,
    )
