"""Hard work bounds before compaction can bypass the cheap floor refusal."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict

from app.domain.entities.chat import Message, ToolDefinition

MAX_COMPACTION_PAYLOAD_BYTES = 8 * 1024 * 1024
COMPACTION_TIMEOUT_SECONDS = 120.0


def payload_exceeds(
    messages: Sequence[Message], tools: Sequence[ToolDefinition], limit: int
) -> bool:
    """Bound UTF-8 bytes, including call arguments and nested tool schemas.

    Incremental encoding avoids making another complete byte copy just to
    reject it. This is a bound on the prompt entering the transformations.
    """
    payload = {
        "messages": [asdict(message) for message in messages],
        "tools": [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in tools
        ],
    }
    size = 0
    for part in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(payload):
        size += len(part.encode("utf-8"))
        if size > limit:
            return True
    return False
