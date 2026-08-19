"""Ollama adapter, against a stubbed transport.

No Ollama required: httpx.MockTransport replays recorded NDJSON, which lets
the parsing and lifecycle rules be pinned without a GPU in the loop.

The cases here are the ones that are invisible until they matter: whether the
upstream request is actually closed on disconnect, and whether token counts
are double-counted at the end of a stream.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.entities.chat import Message, MessageRole

MESSAGES = [Message(role=MessageRole.USER, content="hello")]


def ndjson(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


@pytest.fixture
def patch_httpx(monkeypatch):
    def apply(handler):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)

    return apply
