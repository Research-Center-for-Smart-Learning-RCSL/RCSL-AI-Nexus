"""OpenAI-compatible request and response shapes.

Deliberately separate from the domain entities: this is a wire contract owned
by other people's client libraries, and it should be able to change (or gain a
second version) without the domain noticing.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TextContentPart(BaseModel):
    """One entry of an array-shaped `content`.

    Only `text` exists here. OpenAI's array form also carries `image_url` and
    audio parts, and a client sending one is refused by this `Literal` rather
    than having the part dropped: the `vision` capability is issuable, so a
    caller could reasonably send an image, and answering it from the text alone
    would look like the model had seen the picture and ignored it. When a
    vision path exists, this is the type that grows a member.
    """

    type: Literal["text"]
    text: str


class ToolCallFunction(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: str = ""
    """JSON text, and not parsed here. It is model output being replayed, so it
    may be malformed, and rejecting the conversation at this layer would make a
    turn the model itself produced impossible to continue."""


class ToolCallIn(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatMessageIn(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[TextContentPart] | None = None
    """Nullable, because an assistant turn that only called a tool has no text.
    Required on every other role; see `_check_shape`."""

    tool_calls: list[ToolCallIn] = Field(default_factory=list)
    """Set on an assistant turn being replayed. An agent client sends the whole
    conversation every time, so this is how the model is reminded what it asked
    for, and it is what a following tool result is paired against."""

    tool_call_id: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> ChatMessageIn:
        """The combinations that are not merely unusual but unanswerable.

        Checked here rather than left to the runtime. Each of these reaches
        Ollama as a request it will either refuse with a message about its own
        internals or, worse, accept and answer from a conversation missing the
        part that gave it meaning.
        """
        if self.tool_calls and self.role != "assistant":
            # Only the assistant asks for tools; the adapters forward this
            # field on whatever role carries it, so a `user` message smuggling
            # one would reach the runtime as a shape no chat template defines
            # and be answered from whatever it makes of it.
            raise ValueError("only an assistant message may carry tool_calls")
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("a tool message must carry tool_call_id")
            if self.content is None:
                raise ValueError("a tool message must carry content")
        elif self.role == "assistant":
            if self.content is None and not self.tool_calls:
                raise ValueError("an assistant message needs content or tool_calls")
        elif self.content is None:
            raise ValueError(f"a {self.role} message must carry content")
        return self


class FunctionDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    """JSON Schema, forwarded to the runtime uninterpreted and never validated
    against the arguments that come back. It counts towards the context limit,
    since it is prompt the model reads like any other."""


class ToolIn(BaseModel):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class ToolChoiceFunctionName(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ToolChoiceObject(BaseModel):
    type: Literal["function"] = "function"
    function: ToolChoiceFunctionName


class StreamOptions(BaseModel):
    include_usage: bool = False
    """Send a final frame carrying token counts before `[DONE]`. Off by
    default, because a client that does not expect it sees a chunk with an
    empty `choices` array."""


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
    messages: list[ChatMessageIn] = Field(min_length=1)
    stream: bool = False
    tools: list[ToolIn] = Field(
        default_factory=list,
        description=(
            "Functions the model may ask to call. The platform never executes "
            "one and never validates a call against its schema: the caller runs "
            "the tool and sends the result back as a message with role 'tool'. "
            "Accepted and silently dropped before 2026-08-05, which meant an "
            "agent client received prose where it expected a call."
        ),
    )
    tool_choice: Literal["auto", "none", "required"] | ToolChoiceObject | None = Field(
        default=None,
        description=(
            "'auto' (the default) and 'none' are honoured exactly. 'required' "
            "and naming a function are refused with 400: they ask the runtime "
            "to constrain decoding so a call is certain, which neither runtime "
            "here exposes, and quietly serving 'auto' instead would answer a "
            "caller who demanded a call with prose."
        ),
    )
    parallel_tool_calls: bool | None = Field(
        default=None,
        description=(
            "Accepted and ignored. Neither runtime offers a way to bound how "
            "many calls a model emits in one turn, and dropping the extras "
            "here would discard output the model produced and the caller paid "
            "for. Listed rather than left to be discovered."
        ),
    )
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int | None = None
    functions: Any | None = Field(default=None, exclude=True)
    function_call: Any | None = Field(default=None, exclude=True)
    """OpenAI's deprecated spellings of `tools` and `tool_choice`, declared so
    they can be *refused* — see `_refuse_legacy_functions`. Undeclared they
    fell to pydantic's `extra="ignore"`, which is the identical silent failure
    `tools` itself had until 2026-08-05: an older client library sends its
    functions, gets 200 and prose, and stalls waiting for a call that was
    never requested. The one shape of compatibility gap this schema exists to
    not have."""
    stop: str | list[str] | None = Field(
        default=None,
        description="Up to four stop sequences, as OpenAI allows. A bare string "
        "is accepted as a list of one.",
    )
    """The count is checked in `_check_stop_count`, deliberately not with
    `max_length` on this field. Pydantic applies a length constraint to every
    member of a union it fits, so `max_length=4` meant "at most four items" for
    the list and **"at most four characters" for the string** — which rejected
    every ordinary stop sequence (`"User:"`, `"\\n\\nObservation:"`) with a 422
    whose message talked about items. Its own test used a three-character value
    and passed."""
    """Forwarded to the runtime, and only when set, so its own defaults stay in
    force otherwise. All four were accepted and silently dropped until
    2026-08-05: `temperature: 0` returned 200 and changed nothing."""

    n: int | None = Field(
        default=None,
        description=(
            "Only 1 is supported; anything else is refused rather than served "
            "as one choice. A caller asking for several samples and receiving "
            "one has no way to tell that from a model that produced identical "
            "text, and the concurrency limiter exists precisely to stop one "
            "request occupying the hardware several times over."
        ),
    )
    stream_options: StreamOptions | None = None
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
    use_knowledge: bool = Field(
        default=False,
        description=(
            "Retrieve from this tenant's knowledge base and ground the answer "
            "on what comes back. Not an OpenAI field, and off by default: "
            "grounding costs an embedding call and a slice of the context "
            "window, so it is asked for rather than assumed. Cited documents "
            "come back in the X-Knowledge-Sources header, not in the frames, "
            "which stay strictly OpenAI-shaped."
        ),
    )
    knowledge_collection: str | None = Field(
        default=None,
        description="Restrict retrieval to one collection. Ignored unless "
        "use_knowledge is set. Never widens the tenant scope, which is fixed "
        "by the caller's key.",
    )

    @model_validator(mode="after")
    def _check_single_choice(self) -> ChatCompletionRequest:
        if self.n is not None and self.n != 1:
            raise ValueError("n must be 1; this platform serves one choice per request")
        return self

    @model_validator(mode="after")
    def _refuse_legacy_functions(self) -> ChatCompletionRequest:
        if self.functions is not None or self.function_call is not None:
            raise ValueError(
                "'functions' and 'function_call' are the deprecated OpenAI "
                "spellings and are not supported; send 'tools' and 'tool_choice'"
            )
        return self

    @model_validator(mode="after")
    def _check_stream_options_need_a_stream(self) -> ChatCompletionRequest:
        """Refused rather than ignored, as OpenAI refuses it. A caller setting
        `include_usage` on a non-streaming request has confused the two paths,
        and silently honouring half their request hides that from them."""
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream: true")
        return self

    @model_validator(mode="after")
    def _check_stop_count(self) -> ChatCompletionRequest:
        """Counted after normalisation, so a bare string is one sequence rather
        than however many characters it has."""
        if len(self.stop_sequences) > 4:
            raise ValueError("stop takes at most four sequences")
        return self

    @property
    def stop_sequences(self) -> tuple[str, ...]:
        if self.stop is None:
            return ()
        if isinstance(self.stop, str):
            return (self.stop,)
        return tuple(self.stop)


class AdminChatMessage(BaseModel):
    """The chat panel's message, which is the gateway's from before tools.

    Its own type rather than `ChatMessageIn`, so that widening the public
    contract does not widen this one by accident. The panel is a person typing
    into a text box: it has no tool to call and no result to return, so
    accepting a `tool` message here would be a shape nothing produces and
    nothing reads, on an endpoint whose whole purpose is to be narrower than
    the public one.
    """

    role: Literal["system", "user", "assistant"]
    content: str


class AdminChatRequest(BaseModel):
    """The management UI's shape, which is not the OpenAI one.

    It names `capability` rather than `model`, because there is no
    compatibility obligation here and the field's meaning was always the
    capability: the gateway keeps the OpenAI spelling so third-party client
    libraries work, and this endpoint has no such caller to accommodate.
    """

    capability: str = Field(min_length=1, max_length=64)
    messages: list[AdminChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, gt=0)
    think: bool | None = Field(default=None)
    """Omitted takes the deployment default. See `ChatCompletionRequest.think`."""
    use_knowledge: bool = False
    knowledge_collection: str | None = None


class ToolCallDelta(BaseModel):
    """One tool call in a streaming delta.

    `index` is what a client accumulates on, and it is required even though
    these are whole calls rather than fragments: a client written against
    OpenAI keys its buffer on it, and two calls arriving without one would be
    concatenated into a single malformed call.
    """

    index: int
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class Delta(BaseModel):
    content: str | None = None
    role: str | None = None
    reasoning_content: str | None = None
    """A thinking model's deliberation. Never merged into `content`: it is not
    the answer, and a client echoing it back as history would feed the model
    its own scratch work."""

    tool_calls: list[ToolCallDelta] | None = None


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
    content: str | None
    """Null when the turn was nothing but tool calls, which is what OpenAI
    sends and what a client replaying this message back to us expects to be
    allowed to send. An empty string would be a claim that the model answered
    and said nothing."""

    tool_calls: list[ToolCallIn] | None = None
    """Absent rather than empty when the model called nothing, so a client that
    branches on the key's presence behaves as it would against OpenAI."""

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
