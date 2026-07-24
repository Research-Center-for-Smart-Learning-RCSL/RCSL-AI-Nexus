"""OpenAI-compatible request and response shapes.

Deliberately separate from the domain entities: this is a wire contract owned
by other people's client libraries, and it should be able to change (or gain a
second version) without the domain noticing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(
        description=(
            "A capability name such as 'chat' or 'code'. Callers ask for a "
            "capability and the routing policy decides which model serves it, "
            "which is what lets models be swapped without touching clients. "
            "The field keeps its OpenAI name so existing libraries work "
            "unchanged."
        )
    )
    messages: list[ChatMessageIn]
    stream: bool = False
    max_tokens: int | None = Field(
        default=None,
        description=(
            "Advisory. The platform applies its own hard ceiling regardless, "
            "since an unbounded generation is a hardware problem rather than a "
            "client preference."
        ),
    )


class Delta(BaseModel):
    content: str | None = None
    role: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


class CompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class Choice(BaseModel):
    index: int = 0
    message: CompletionMessage
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
