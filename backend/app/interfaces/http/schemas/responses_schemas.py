"""The subset of OpenAI's Responses API that a coding agent actually sends.

**Why this exists at all.** Codex removed `wire_api = "chat"` in February 2026
and speaks only the Responses API; the gateway served only
`/v1/chat/completions`. The runbook this repository shipped on 2026-08-05 told
integrators to set `wire_api = "chat"`, six months after that stopped being
possible — which is what happens when a client is designed for and never run.

**This is a subset, and deliberately.** The shapes here were not read from the
specification: they were captured off the wire from `codex-cli 0.147.0` driving
a local recorder (PROGRESS.md 2026-08-07), so every field is one a real client
sent. Anything the specification allows and Codex does not send is absent, and
adding it on speculation would be inventing a contract nobody has tested.

Two shapes differ from Chat Completions in ways that are easy to get subtly
wrong:

- `instructions` is a **top-level string**, not a system message. It arrives
  beside `input` rather than inside it.
- A tool is **flat** — `{"type": "function", "name": ..., "parameters": ...}` —
  where Chat Completions nests it under a `function` key.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- input items -------------------------------------------------------------


class InputTextPart(BaseModel):
    """`input_text` is what Codex sends for every message part.

    `output_text` appears on the *response* side; it is accepted here too
    because a client replaying its own previous turn back into `input` is the
    ordinary way this API carries history.
    """

    type: Literal["input_text", "output_text", "text"]
    text: str


class InputMessage(BaseModel):
    type: Literal["message"] = "message"
    role: str
    # A bare string is legal in the API and Codex always sends parts. Both are
    # accepted because rejecting the simpler form would refuse a request no
    # rule anywhere calls invalid.
    content: str | list[InputTextPart]
    id: str | None = None


class InputFunctionCall(BaseModel):
    """The model's own previous call, replayed by the client.

    `call_id` is the correlation key, not `id`: `id` identifies the item and
    `call_id` is what the matching `function_call_output` refers to. Codex
    sends both and they differ.
    """

    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: str
    id: str | None = None


class InputFunctionCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    # A string in every capture, including the one carrying a tool error.
    # Structured output is permitted by the API; it is coerced to text at the
    # boundary rather than refused, since a runtime takes a string either way.
    output: str | list[InputTextPart] | dict[str, object]
    id: str | None = None


class InputReasoning(BaseModel):
    """Emitted when `include: ["reasoning.encrypted_content"]` is asked for.

    Accepted and discarded. It is a model's own deliberation from an earlier
    turn, which this platform never replays into a prompt — the same rule
    `CompletionChunk.reasoning` states for the streaming side.
    """

    model_config = ConfigDict(extra="allow")
    type: Literal["reasoning"] = "reasoning"
    id: str | None = None


InputItem = Annotated[
    InputMessage | InputFunctionCall | InputFunctionCallOutput | InputReasoning,
    Field(discriminator="type"),
]


# --- tools -------------------------------------------------------------------


class FunctionTool(BaseModel):
    """Flat, unlike Chat Completions' nested `{"function": {...}}`."""

    type: Literal["function"] = "function"
    name: str
    description: str | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    strict: bool | None = None


class NamespaceTool(BaseModel):
    """A container of ordinary function tools, not a capability of its own.

    Codex sends `multi_agent_v1` this way, holding `spawn_agent`, `wait_agent`,
    `send_input`, `resume_agent` and `close_agent`. Every one is executed by the
    *client*, exactly like `exec_command`, so supporting this needs nothing from
    the platform beyond flattening it — which is why these are not refused.
    """

    type: Literal["namespace"] = "namespace"
    name: str
    description: str | None = None
    tools: list[FunctionTool] = Field(default_factory=list)


class WebSearchTool(BaseModel):
    """A **server-side** tool: the provider performs the search.

    This is the one thing in a Codex request the platform genuinely cannot do.
    Supporting it would mean the gateway making outbound web requests, which is
    a new capability and a direct conflict with the data plane's network
    segmentation (security.md §6) and its SSRF stance (§7.2).

    `external_web_access` decides whether that matters. Codex sends `false` by
    default, which is the client saying the tool is off; dropping something
    already declared disabled is equivalent to honouring it. `true` is a real
    request for a real capability, and is refused rather than served silently —
    the rule `MLX_TOOL_CALLING_VERIFIED` established for tool calling itself.
    """

    type: Literal["web_search"] = "web_search"
    external_web_access: bool = False


class UnknownTool(BaseModel):
    """Anything else the client offers.

    Kept rather than rejected so that a future Codex adding a tool type does not
    turn every request into a 422. It is dropped with the others and reported in
    the `X-Dropped-Tools` header, so a capability the model never sees is
    visible to whoever is wondering why.
    """

    model_config = ConfigDict(extra="allow")
    type: str


ToolItem = FunctionTool | NamespaceTool | WebSearchTool | UnknownTool


# --- request -----------------------------------------------------------------


class ToolChoiceFunction(BaseModel):
    type: Literal["function"] = "function"
    name: str


class ReasoningOptions(BaseModel):
    model_config = ConfigDict(extra="allow")
    effort: str | None = None
    summary: str | None = None


class ResponsesRequest(BaseModel):
    """Extra fields are ignored, not refused.

    `prompt_cache_key`, `client_metadata`, `include`, `store` and
    `parallel_tool_calls` all arrive from Codex and none has meaning here: this
    gateway holds no state between requests, so there is nothing to cache or
    store. Refusing them would refuse every real client, and `extra="ignore"`
    is pydantic's default — stated explicitly because the same default silently
    dropped `tools` on the chat endpoint until 2026-08-05, and being deliberate
    about it is the difference.
    """

    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[InputItem]
    instructions: str | None = None
    tools: list[ToolItem] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] | ToolChoiceFunction | None = None
    stream: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    reasoning: ReasoningOptions | None = None

    # Non-OpenAI, and the same two fields the chat endpoint carries. Named here
    # so an agent client can reach knowledge grounding and prompt templates
    # without a second endpoint shape to learn.
    use_knowledge: bool = False
    knowledge_collection: str | None = None
    prompt_template: str | None = None
    think: bool | None = None


# --- response ----------------------------------------------------------------


class OutputTextPart(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[dict[str, object]] = Field(default_factory=list)


class OutputMessage(BaseModel):
    type: Literal["message"] = "message"
    id: str
    role: Literal["assistant"] = "assistant"
    status: Literal["completed", "incomplete"] = "completed"
    """An item's own status, which is not always the response's: a message
    closed because a tool call began is complete, in a response that is still
    running. `"incomplete"` is the one that was missing — it marks the text
    that was cut off, next to the `incomplete_details` on the response."""
    content: list[OutputTextPart]


class OutputFunctionCall(BaseModel):
    type: Literal["function_call"] = "function_call"
    id: str
    call_id: str
    name: str
    arguments: str
    status: Literal["completed"] = "completed"


class ResponseUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponsePayload(BaseModel):
    """The `response` object, both as the non-streaming body and inside events."""

    id: str
    object: Literal["response"] = "response"
    created_at: int
    status: Literal["in_progress", "completed", "incomplete", "failed"]
    model: str
    output: list[OutputMessage | OutputFunctionCall] = Field(default_factory=list)
    usage: ResponseUsage | None = None
    # `Any`, not `object`: this model has a field called `object`, which
    # shadows the builtin inside the class body.
    error: dict[str, Any] | None = None
    incomplete_details: dict[str, Any] | None = None
