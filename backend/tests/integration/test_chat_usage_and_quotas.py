from __future__ import annotations

import pytest

from app.domain.entities.model import RuntimeKind
from tests.integration.chat_end_to_end_fixtures import (
    TEST_DATABASE_URL,
    StubRuntime,
    issue_key,
)

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.chat_end_to_end_fixtures",)


async def test_quota_is_enforced(client) -> None:
    """Dead in two independent ways: the quota was read off a repository that
    has no such method (silently returning zero), and no usage row carried the
    key it belonged to."""
    test_client, _, _ = client
    token = await issue_key(quota_tokens_per_day=2)
    test_client.headers["Authorization"] = f"Bearer {token}"

    body = {"model": "chat", "messages": [{"role": "user", "content": "hi"}]}

    first = test_client.post("/v1/chat/completions", json=body)
    assert first.status_code == 200, "the first request is within quota"

    second = test_client.post("/v1/chat/completions", json=body)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    assert second.headers["Retry-After"]


async def test_an_exhausted_quota_does_not_present_itself_as_a_rate_limit(client) -> None:
    """The two conditions that share 429 have opposite remedies, and a client
    library reads `type` rather than `code` to decide which it is looking at.
    Announcing a spent quota as `rate_limit_error` asks for a retry that cannot
    succeed; that is how a Codex session against key 68953ceb on 2026-08-14
    turned an exhausted budget into `exceeded retry limit, last status: 429`.

    `Retry-After` is asserted against the window rather than merely for its
    presence, because the value it used to carry — a fixed hour — was present
    and wrong. The window trails 24 hours, so the single usage row written by
    the request above leaves it roughly a day from now.
    """
    test_client, _, _ = client
    token = await issue_key(quota_tokens_per_day=2)
    test_client.headers["Authorization"] = f"Bearer {token}"

    body = {"model": "chat", "messages": [{"role": "user", "content": "hi"}]}
    assert test_client.post("/v1/chat/completions", json=body).status_code == 200

    refused = test_client.post("/v1/chat/completions", json=body)
    assert refused.status_code == 429
    assert refused.json()["error"]["type"] == "insufficient_quota"
    assert 86_000 < int(refused.headers["Retry-After"]) <= 86_400
    assert "recovers in about 24 hours" in refused.json()["error"]["message"]


async def test_the_model_list_survives_an_exhausted_quota(client) -> None:
    """A token quota has nothing to charge for a call that runs no model, and
    every OpenAI-compatible client asks for this list before it can send its
    first request. Refusing it turned "this key is out of budget" into "this
    agent cannot connect", which is a different problem to debug and points at
    the wrong half of the system.
    """
    test_client, _, _ = client
    token = await issue_key(quota_tokens_per_day=2)
    test_client.headers["Authorization"] = f"Bearer {token}"

    body = {"model": "chat", "messages": [{"role": "user", "content": "hi"}]}
    assert test_client.post("/v1/chat/completions", json=body).status_code == 200
    assert test_client.post("/v1/chat/completions", json=body).status_code == 429

    listed = test_client.get("/v1/models")
    assert listed.status_code == 200
    assert listed.json()["data"], "the list is the point; an empty one is no better than a 429"


async def test_the_model_list_still_refuses_an_invalid_key(client) -> None:
    """The quota is the only check the metadata path drops. Asserted here
    because the exemption is expressed as a second dependency, and the way that
    fails is by quietly skipping more than it meant to."""
    test_client, _, _ = client
    test_client.headers["Authorization"] = "Bearer nx_live_deadbeefdeadbeef.notarealsecret"

    assert test_client.get("/v1/models").status_code == 401


async def test_the_envelope_reports_prompt_tokens(client) -> None:
    """`prompt_tokens` was the schema default of 0 on every response until
    2026-08-04, while the runtime was reporting a real figure all along. An
    OpenAI client computes cost from these three numbers, so a zero here is a
    wrong answer rather than a missing one."""
    test_client, _, _ = client
    test_client.app.state.runtimes = {RuntimeKind.OLLAMA: StubRuntime(chunks=3, prompt_tokens=34)}

    response = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["prompt_tokens"] == 34
    assert usage["completion_tokens"] == 3
    assert usage["total_tokens"] == 37, "the total is both halves, not the generated half"


async def test_quota_counts_the_prompt_as_well_as_the_answer(client) -> None:
    """Charging for output alone let a caller fill the context window on every
    request and spend none of its quota doing it, which on this hardware is
    most of the work. One request of 3 generated + 34 read exceeds a quota of
    10; before, it counted as 3 and the key would have run all day."""
    test_client, _, _ = client
    test_client.app.state.runtimes = {RuntimeKind.OLLAMA: StubRuntime(chunks=3, prompt_tokens=34)}
    token = await issue_key(quota_tokens_per_day=10)
    test_client.headers["Authorization"] = f"Bearer {token}"

    body = {"model": "chat", "messages": [{"role": "user", "content": "hi"}]}

    first = test_client.post("/v1/chat/completions", json=body)
    assert first.status_code == 200, "the first request is still within quota"

    second = test_client.post("/v1/chat/completions", json=body)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"


async def test_rate_limit_is_enforced(client) -> None:
    """`rate_limit_rpm` was persisted end to end and enforced nowhere."""
    test_client, _, _ = client
    token = await issue_key(rate_limit_rpm=2)
    test_client.headers["Authorization"] = f"Bearer {token}"

    body = {"model": "chat", "messages": [{"role": "user", "content": "hi"}]}
    statuses = [test_client.post("/v1/chat/completions", json=body).status_code for _ in range(4)]

    assert statuses[:2] == [200, 200]
    assert 429 in statuses[2:], f"rate limit never fired: {statuses}"


async def test_truncation_reports_length_not_stop(client) -> None:
    """Reporting `stop` for a generation we cut off is an active lie: OpenAI
    clients branch on this field to decide whether to continue a reply."""
    test_client, _, _ = client
    test_client.app.state.runtimes = {RuntimeKind.OLLAMA: StubRuntime(chunks=100)}

    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "chat",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["finish_reason"] == "length"
