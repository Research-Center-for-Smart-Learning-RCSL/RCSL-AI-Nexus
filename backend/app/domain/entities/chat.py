"""Chat primitives that cross the runtime port.

The domain emits `CompletionChunk`, never SSE-formatted strings. Wire framing
belongs to the interface layer, which is what lets one use case serve both the
OpenAI-compatible gateway endpoint and the admin chat endpoint.
See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    """The result of a tool the assistant asked for.

    Distinct from USER even though both carry text the model reads. An agent
    client replays the whole conversation on every turn, and a tool result
    relabelled as something the person said is a result the model can no
    longer attribute to the call it made.
    """


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    """The model's arguments as JSON *text*, deliberately not parsed here.

    It is model output, so it can be malformed, and the caller that has to
    recover from that needs the bytes the model produced rather than this
    platform's re-encoding of a parse that may have succeeded by accident. A
    runtime that hands back a decoded object is re-encoded at the adapter
    boundary, which is where a runtime's spelling belongs.
    """


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema, forwarded to the runtime uninterpreted.

    The platform never validates a tool call against it. A schema validator in
    the inference path would buy nothing the caller cannot do itself: the
    caller is what executes the tool, and it has to handle a model that got the
    arguments wrong whether or not this layer noticed first.
    """


class ToolChoiceMode(StrEnum):
    AUTO = "auto"
    NONE = "none"
    REQUIRED = "required"
    FUNCTION = "function"


@dataclass(frozen=True, slots=True)
class ToolChoice:
    mode: ToolChoiceMode = ToolChoiceMode.AUTO
    function_name: str | None = None
    """Set only for FUNCTION, naming the one tool the caller demands.

    Whether a mode can be honoured is the runtime's answer, not this layer's:
    NONE is exact everywhere (the tools are simply not sent), while REQUIRED
    and FUNCTION need the runtime to constrain decoding. An adapter that cannot
    refuses, rather than downgrading to AUTO — a caller who demanded a tool call
    and silently received prose gets a parse failure somewhere further away.
    """


@dataclass(frozen=True, slots=True)
class SamplingOptions:
    """Decoding parameters the caller may set, all optional.

    One object rather than four arguments threaded through the port, the use
    case and every adapter: the set grows, and each addition would otherwise be
    a signature change at every layer. `None` means "the caller expressed no
    preference", which is not the same as any particular value — a runtime is
    sent only what was actually asked for, so its own default stays in force.
    """

    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()
    seed: int | None = None

    def is_empty(self) -> bool:
        return (
            self.temperature is None and self.top_p is None and not self.stop and self.seed is None
        )


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    """Set on an ASSISTANT message that asked for tools.

    Beside `content` rather than flattened into it. An agent client sends this
    message back verbatim on the next turn, and a tool call rendered as prose
    is one the runtime can no longer pair with the TOOL message that answers
    it, so the model sees a result for a call it has no record of making.
    """

    tool_call_id: str | None = None
    """Set on a TOOL message, naming the call it answers."""

    name: str | None = None
    """The tool's name on a TOOL message. Carried as well as `tool_call_id`
    because runtimes differ on which of the two they pair on; the id is the
    authoritative link where both are honoured."""


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    delta: str
    """Incremental text. Empty on a chunk that only carries a finish reason."""

    finish_reason: str | None = None
    token_count: int = 0
    """Tokens represented by this chunk. Summed to record usage even when a
    stream ends early, so a client disconnect still bills what was produced."""

    prompt_tokens: int = 0
    """Tokens the model *read*, carried once on the terminal chunk.

    On the terminal chunk only because a runtime reports it once, at the end,
    for the whole request — it is not incremental like `token_count`, and
    summing it per chunk would multiply it by the length of the stream.

    Recorded separately from `token_count` rather than folded into it because
    the two are different work at different prices, and because an OpenAI
    client reads `prompt_tokens` and `completion_tokens` as distinct fields.
    Zero when a runtime does not report it, which is honest: unknown and none
    are the same number here, and the alternative was reporting a made-up one.
    Counted nowhere at all until 2026-08-04, which left `quota_tokens_per_day`
    charging for output only — a caller could send a context-filling prompt
    every time and never spend quota on it."""

    reasoning: str = ""
    """Incremental reasoning from a thinking model, kept separate from `delta`.

    Separate because it is not the answer: concatenating the two would put a
    model's private deliberation into the reply, and into the conversation
    history a client sends back on the next turn. It is a distinct field rather
    than a dropped one because a thinking model can spend its entire token
    budget here — a stream that carries reasoning and nothing else is the
    normal case for a hard question, and a transport that emits nothing for it
    is silent for as long as the model thinks. That silence is what an
    intermediary's idle timeout kills. See docs/PROGRESS.md, 2026-07-27."""

    tool_calls: tuple[ToolCall, ...] = ()
    """Tool calls the model emitted on this chunk.

    Whole calls, never fragments. OpenAI streams a call's `arguments` as a
    series of partial strings the client concatenates; both runtimes here
    report a complete call in a single event instead, and inventing
    intermediate fragments to imitate the wire would be a shape no runtime
    actually produced. The interface layer emits each of these as one
    `delta.tool_calls` entry, which a client that concatenates handles
    correctly — concatenating a single piece is that piece.

    A chunk carrying tool calls usually carries no `delta`: a model that has
    decided to call something answers with the call rather than with prose.
    """
