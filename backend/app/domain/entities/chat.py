"""Chat primitives that cross the runtime port.

The domain emits `CompletionChunk`, never SSE-formatted strings. Wire framing
belongs to the interface layer, which is what lets one use case serve both the
OpenAI-compatible gateway endpoint and the admin chat endpoint.
See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str


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
