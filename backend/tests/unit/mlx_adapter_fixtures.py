"""MLX adapter, against a stubbed transport and stubbed download seams.

No MLX, no GPU, and no HuggingFace access: httpx.MockTransport replays OpenAI SSE
for the inference path, and the three download seams are replaced for `pull`.

The cases that matter are the ones invisible until they bite: whether the
upstream request is actually closed on disconnect, whether the end-of-stream
token count is reconciled rather than double-counted, and whether `unload`
refuses rather than lying about having freed memory.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.entities.chat import Message, MessageRole

MESSAGES = [Message(role=MessageRole.USER, content="hello")]

REF = "mlx-community/Qwen2.5-7B-Instruct-4bit"


def sse(*events: dict | str) -> bytes:
    """Frame events as OpenAI SSE. A plain string is emitted verbatim, for
    `[DONE]` and malformed lines."""
    lines = []
    for event in events:
        payload = event if isinstance(event, str) else json.dumps(event)
        lines.append(f"data: {payload}")
    return ("\n\n".join(lines) + "\n\n").encode()


def _chunk(content: str = "", finish_reason: str | None = None) -> dict:
    return {
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish_reason}]
    }


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


class _Lfs:
    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256


class _Sibling:
    def __init__(self, rfilename: str, *, sha256: str | None = None, blob_id: str | None = None):
        self.rfilename = rfilename
        self.lfs = _Lfs(sha256) if sha256 else None
        self.blob_id = blob_id
        self.size = 0


def _hub(siblings: list[_Sibling]) -> object:
    class FakeInfo:
        def __init__(self) -> None:
            self.siblings = siblings

    class FakeApi:
        def model_info(self, ref: str, files_metadata: bool = False) -> FakeInfo:
            return FakeInfo()

    class FakeHub:
        HfApi = FakeApi

    return FakeHub
