from __future__ import annotations

import json

import pytest

from tests.integration.chat_end_to_end_fixtures import (
    TEST_DATABASE_URL,
    count_usage,
    issue_key,
)

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.chat_end_to_end_fixtures",)


async def test_models_lists_the_capabilities_this_key_can_call(client) -> None:
    """Every OpenAI client library calls this on startup and used to get a 404.
    It answers with capabilities, which is what the `model` field takes."""
    test_client, _, _ = client

    response = test_client.get("/v1/models")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "list"
    # `vision` is in the key's list but no policy serves it, so it is absent:
    # the list answers "what can I call", not "what was I issued".
    assert [entry["id"] for entry in body["data"]] == ["chat", "code"]
    assert all(entry["object"] == "model" for entry in body["data"])
    # Nothing about which model, runtime or node is behind the capability.
    assert "qwen" not in json.dumps(body).lower()
    assert "primary" not in json.dumps(body)


async def test_models_is_narrowed_to_the_calling_key(client) -> None:
    test_client, _, _ = client
    token = await issue_key(scopes=frozenset({"code"}))
    test_client.headers["Authorization"] = f"Bearer {token}"

    response = test_client.get("/v1/models")

    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()["data"]] == ["code"]


async def test_models_requires_a_key(client) -> None:
    """Otherwise what a deployment serves is a free answer to anyone asking."""
    test_client, _, _ = client
    del test_client.headers["Authorization"]

    assert test_client.get("/v1/models").status_code == 401


async def test_a_key_cannot_reach_a_capability_it_was_not_issued_for(client) -> None:
    """The stored capability list decided only whether a key worked at all,
    never which capability it could ask for, so a key issued for `chat` reached
    every capability the deployment could route. The issuing form presents the
    field as what the key may do.
    """
    test_client, _, _ = client
    token = await issue_key(scopes=frozenset({"chat"}))
    test_client.headers["Authorization"] = f"Bearer {token}"

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "code", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    # Its own code since 2026-08-14, on the rule the `no_available_model` split
    # already followed: a separate remedy earns a separate code. This one means
    # "change the `model` field", where a bare `not_authorized` means "you may
    # not do this at all", and a client cannot give both pieces of advice.
    assert response.json()["error"]["code"] == "capability_not_issued"
    # Not reported as a capacity problem: this one the caller can fix.
    assert response.json()["error"]["code"] != "no_available_model"


async def test_a_key_issued_for_one_capability_can_use_it(client) -> None:
    """Only `chat` mapped onto a scope, so a key issued for `code` alone held
    no scopes and was refused everything — a choice the form offered and the
    gateway could not honour."""
    test_client, _, _ = client
    token = await issue_key(scopes=frozenset({"code"}))
    test_client.headers["Authorization"] = f"Bearer {token}"

    allowed = test_client.post(
        "/v1/chat/completions",
        json={"model": "code", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert allowed.status_code == 200, allowed.text

    refused = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert refused.status_code == 403


async def test_a_capability_refusal_names_what_the_key_may_call(client) -> None:
    """The refusal an integrator can act on without reading our logs.

    On 2026-08-14 two Codex users sent the model name their own client had
    picked — `gpt-5.6-sol` — and got "You do not have permission to perform
    this action.", while the reason sat in the gateway log where they could not
    reach it. The `model` field taking a capability is this platform's one real
    divergence from every other provider, and this refusal is where somebody
    meets it.

    Safe to say because it is not new information: the caller sent the
    capability, and the list is what `GET /v1/models` already returns to the
    same key.
    """
    test_client, _, _ = client

    token = await issue_key(scopes=frozenset({"code"}))
    test_client.headers["Authorization"] = f"Bearer {token}"

    refused = test_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert refused.status_code == 403
    error = refused.json()["error"]
    assert error["code"] == "capability_not_issued"
    assert "gpt-5.6-sol" in error["message"]
    assert "code" in error["message"]
    # The wider rule still holds: which model serves a capability is not
    # disclosed, and naming the capability does not start naming the model.
    assert "primary" not in json.dumps(refused.json())


async def test_a_key_with_a_default_capability_is_served_and_told_so(client) -> None:
    """The opt-in escape from the refusal above, end to end.

    The whole case for allowing it per key rather than deployment-wide is that
    it stays visible, so the header is asserted beside the answer: a caller
    that reads it can still discover their client is sending a model name, and
    an operator reading a capture can tell which requests were substituted.
    """
    test_client, _, _ = client

    token = await issue_key(scopes=frozenset({"chat"}), default_capability="chat")
    test_client.headers["Authorization"] = f"Bearer {token}"

    served = test_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert served.status_code == 200
    assert served.headers["X-Capability-Defaulted"] == "chat"
    # Echoed as it arrived. A client matching the echo against what it sent is
    # entitled to, and the substitution is already stated in the header.
    assert served.json()["model"] == "gpt-5.6-luna"


async def test_a_default_capability_does_not_widen_what_a_key_may_reach(client) -> None:
    """A row that named a capability outside the key's own list would have to
    have arrived by a direct write — `ManageApiKeys` refuses the pair — and it
    still decides nothing when it does."""
    test_client, _, _ = client

    token = await issue_key(scopes=frozenset({"chat"}), default_capability="code")
    test_client.headers["Authorization"] = f"Bearer {token}"

    refused = test_client.post(
        "/v1/chat/completions",
        json={"model": "code", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "capability_not_issued"
    assert "X-Capability-Defaulted" not in refused.headers


async def test_streaming_usage_is_persisted(client) -> None:
    """A streaming response is produced after the endpoint returns, so this
    asserts the session outlives it and the row is actually committed. No test
    checked this, and the declared FastAPI floor included versions where it
    silently did not hold."""
    test_client, _, _ = client
    assert await count_usage() == 0

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert response.status_code == 200

    assert await count_usage() == 1, "streaming usage was not committed"
