"""HTTP encoding boundary."""

from __future__ import annotations

import json
import time
import uuid


def new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def created_now() -> int:
    return int(time.time())


def event(name: str, payload: dict[str, object]) -> str:
    """Both the `event:` line and a `type` inside the data.

    Clients read one or the other and the API sends both; a client keyed on the
    field this omitted would see a stream of events it could not classify.
    """
    body = {"type": name, **payload}
    return f"event: {name}\ndata: {json.dumps(body, separators=(',', ':'))}\n\n"


def _message_item(item_id: str, text: str, status: str = "completed") -> dict[str, object]:
    return {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "status": status,
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _call_item(item_id: str, call_id: str, name: str, arguments: str) -> dict[str, object]:
    return {
        "type": "function_call",
        "id": item_id,
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }
