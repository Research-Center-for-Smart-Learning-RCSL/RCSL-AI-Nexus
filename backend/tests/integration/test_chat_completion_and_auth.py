from __future__ import annotations

import json

import pytest

from tests.integration.chat_end_to_end_fixtures import (
    TEST_DATABASE_URL,
    _sse_events,
    issue_key,
)

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.chat_end_to_end_fixtures",)


async def test_streaming_completion(client) -> None:
    test_client, runtime, _ = client

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _sse_events(response.text)
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events)
    assert text == "tok0 tok1 tok2 "
    assert response.text.rstrip().endswith("data: [DONE]")

    # The policy resolved the capability to a model alias, and the adapter was
    # handed that model's runtime reference rather than the capability name.
    assert runtime.seen_ref == "qwen2.5:7b"


async def test_non_streaming_completion_uses_the_same_path(client) -> None:
    test_client, runtime, _ = client

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "tok0 tok1 tok2 "
    assert body["usage"]["total_tokens"] == 3
    assert body["object"] == "chat.completion"


async def test_missing_key_is_rejected(client) -> None:
    test_client, _, _ = client
    del test_client.headers["Authorization"]

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_a_forged_key_is_rejected(client) -> None:
    """Correct shape, wrong secret. The digest comparison is the only thing
    standing between a guessed key id and access."""
    test_client, _, holder = client
    real = holder["token"]
    key_id = real[len("nx_live_") : real.index(".")]
    test_client.headers["Authorization"] = f"Bearer nx_live_{key_id}.forged-secret"

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401


async def test_unknown_capability_reports_no_available_model(client) -> None:
    test_client, _, _ = client

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "vision", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "no_available_model"
    # The error must not name what was considered.
    assert "primary" not in json.dumps(body)
    assert "qwen" not in json.dumps(body).lower()


async def test_a_key_without_the_chat_scope_is_refused(client) -> None:
    """Scopes were computed and then never consulted, so any valid key could
    consume the hardware regardless of what it was issued for."""
    test_client, _, _ = client
    token = await issue_key(scopes=frozenset())
    test_client.headers["Authorization"] = f"Bearer {token}"

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authorized"
