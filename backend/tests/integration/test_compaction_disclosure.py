"""The compaction disclosure, over a real socket.

The unit tests assert that the use case reports a compaction and that the helper
renders a header from it. Neither can show the thing that was actually in doubt:
whether the header survives to the response at all.

It is not obvious that it can. Compaction happens inside the concurrency slot,
after routing and counting, which is downstream of everything a handler does
before it returns — and on a streaming response the headers close the moment the
body opens. What makes it possible is that `sse.prime` pulls the first chunk
while the response object still does not exist, so there is a window where the
fact is known and the headers are not yet written. These tests are the assertion
that the window is real and that both paths are inside it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.model import RuntimeKind
from app.infrastructure.config import get_settings
from tests.integration.chat_end_to_end_fixtures import (
    PEPPER,
    TEST_DATABASE_URL,
    StubRuntime,
    _seed,
)

pytestmark = pytest.mark.anyio


# 8 ASCII characters per token at the floor, about 4 at the estimate, so a
# ceiling between the two is a prompt the pre-slot bound admits and the real
# count refuses — which is precisely the band compaction exists for. Anything
# below the floor would be refused before a model was ever chosen.
CEILING = 10_000
TOOL_RESULT_CHARS = 2_000
TURNS = 15


@pytest.fixture
async def compacting_client(monkeypatch):
    """The gateway with a low context ceiling, so an ordinary payload compacts."""
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL or "")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("API_KEY_PEPPER", PEPPER)
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    monkeypatch.setenv("MAX_CONTEXT_LENGTH", str(CEILING))
    get_settings.cache_clear()

    holder: dict = {}
    await _seed(holder)

    from app.infrastructure.main_gateway import create_app

    app = create_app()
    runtime = StubRuntime()
    with TestClient(app) as test_client:
        app.state.runtimes = {RuntimeKind.OLLAMA: runtime}
        test_client.headers["Authorization"] = f"Bearer {holder['token']}"
        yield test_client, runtime

    get_settings.cache_clear()


def _agent_payload() -> list[dict]:
    """A conversation whose bulk is tool output, which is the shape Tier 1 is
    for and the shape agent traffic actually has."""
    messages: list[dict] = [{"role": "system", "content": "you use tools"}]
    for i in range(TURNS):
        messages.append(
            {
                "role": "assistant",
                "content": f"calling search, attempt {i}",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": "f" * TOOL_RESULT_CHARS,
            }
        )
    messages.append({"role": "user", "content": "so what is the answer?"})
    return messages


async def test_a_compacted_non_streaming_response_carries_the_header(compacting_client) -> None:
    test_client, _ = compacting_client

    served = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": _agent_payload()},
    )

    assert served.status_code == 200
    assert served.headers["X-Context-Compacted"] == "tier=1"


async def test_a_compacted_streaming_response_carries_the_header(compacting_client) -> None:
    """The path where it was not obvious this could work: the header is written
    with the response's first byte, and the compaction is known only after
    priming — which happens, deliberately, before the response object exists."""
    test_client, _ = compacting_client

    with test_client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "chat", "messages": _agent_payload(), "stream": True},
    ) as served:
        assert served.status_code == 200
        assert served.headers["X-Context-Compacted"] == "tier=1"
        served.read()


async def test_an_ordinary_request_carries_no_such_header(compacting_client) -> None:
    """Absent rather than present and empty, like every other narrowing header
    on this endpoint."""
    test_client, _ = compacting_client

    served = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert served.status_code == 200
    assert "X-Context-Compacted" not in served.headers


async def test_the_model_was_sent_the_reduced_prompt(compacting_client) -> None:
    """The header is only honest if it describes what happened. The stub records
    what it was asked to generate from, so this is the one assertion that the
    reduction reached the runtime rather than being announced and skipped."""
    test_client, runtime = compacting_client

    test_client.post("/v1/chat/completions", json={"model": "chat", "messages": _agent_payload()})

    sent = runtime.seen_messages
    markers = [m for m in sent if "tool result removed" in (m.content or "")]
    assert markers, "no tool result was replaced, so nothing was actually compacted"
    # The most recent turns are untouched: the window protects what the model is
    # currently reasoning about.
    assert sent[-1].content == "so what is the answer?"
