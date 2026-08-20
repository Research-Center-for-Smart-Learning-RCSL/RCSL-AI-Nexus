from __future__ import annotations

import pytest

from app.domain.entities.model import RuntimeKind
from tests.integration.chat_end_to_end_fixtures import (
    TEST_DATABASE_URL,
    StubRuntime,
    _sse_events,
)

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.chat_end_to_end_fixtures",)


async def test_client_max_tokens_is_honoured_when_stricter(client) -> None:
    """It was parsed and discarded, so a caller asking for 3 tokens was billed
    for up to the platform ceiling."""
    test_client, runtime, _ = client
    test_client.app.state.runtimes = {RuntimeKind.OLLAMA: (runtime := StubRuntime(chunks=100))}

    test_client.post(
        "/v1/chat/completions",
        json={
            "model": "chat",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
        },
    )

    assert runtime.seen_max_tokens == 5, "the limit never reached the runtime"


async def test_a_pre_generation_failure_on_the_streaming_path_still_returns_503(client) -> None:
    """The role frame used to be emitted before anything could fail, so the
    status was committed as 200 and routing failures were reported in-band as
    successes while the identical non-streaming request returned 503."""
    test_client, _, _ = client

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "vision", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_available_model"


async def test_grounding_is_off_unless_asked_for(client) -> None:
    """Grounding costs an embedding call and a slice of the context window, so
    an API caller who never asked for it must not get it."""
    test_client, runtime, _ = client
    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )

    assert response.status_code == 200
    assert "X-Knowledge-Sources" not in response.headers
    assert [m.role.value for m in runtime.seen_messages] == ["user"]


async def test_a_request_asking_for_knowledge_still_answers_with_no_index(client) -> None:
    """The whole degradation path, end to end: there is no embedding policy and
    no Qdrant in this environment, and an ordinary completion still comes back.
    Retrieval is an enhancement to the request, not the request."""
    test_client, _, _ = client
    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "use_knowledge": True,
        },
    )

    assert response.status_code == 200
    events = _sse_events(response.text)
    assert "".join(e["choices"][0]["delta"].get("content", "") for e in events if e.get("choices"))
    # Nothing was retrieved, so nothing is cited. A header naming sources that
    # did not exist would be worse than its absence.
    assert "X-Knowledge-Sources" not in response.headers
