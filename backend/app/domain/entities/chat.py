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
