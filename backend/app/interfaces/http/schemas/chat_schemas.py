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
    think: bool | None = Field(
        default=None,
        description=(
            "Not part of the OpenAI schema; an extension, because there is no "
            "standard field for it and the alternative is a caller with no way "
            "to reach the behaviour at all. Omit to take the deployment "
            "default. `false` asks a deliberating model to answer directly, "
            "which is the difference between an answer and none on a question "
            "the model will not stop reasoning about. `true` means 'leave the "
            "model alone' rather than 'think harder' — the runtimes offer no "
            "way to ask for more deliberation, and the graded settings some "
            "advertise measurably do nothing."
        ),
    )


class AdminChatRequest(BaseModel):
    """The management UI's shape, which is not the OpenAI one.

    It names `capability` rather than `model`, because there is no
    compatibility obligation here and the field's meaning was always the
    capability: the gateway keeps the OpenAI spelling so third-party client
    libraries work, and this endpoint has no such caller to accommodate.
    """

    capability: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessageIn] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, gt=0)
    think: bool | None = Field(default=None)
    """Omitted takes the deployment default. See `ChatCompletionRequest.think`."""


class Delta(BaseModel):
    content: str | None = None
    role: str | None = None
    reasoning_content: str | None = None
    """A thinking model's deliberation. Never merged into `content`: it is not
    the answer, and a client echoing it back as history would feed the model
    its own scratch work."""


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
    reasoning_content: str | None = None
    """Present only when the model produced reasoning. Carried on the
    non-streaming path too, so `stream: false` against a thinking model does
    not answer with an empty `content` and no indication of where the tokens
    went."""


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


class ModelCard(BaseModel):
    """One entry of `GET /v1/models`.

    `id` is a capability, which is what this platform's `model` field takes.
    The shape is OpenAI's because client libraries parse it; the contents are
    ours, and deliberately carry nothing about which model, runtime or node
    serves the capability. That is the whole point of routing by capability,
    and it is also what the gateway's error messages are careful not to leak.
    """

    id: str
    object: Literal["model"] = "model"
    created: int = 0
    """Zero rather than a timestamp. A capability has no creation date, and
    inventing one from the policy's would make it look like a version."""

    owned_by: str = "rcsl-ai-nexus"


class ModelListResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]
