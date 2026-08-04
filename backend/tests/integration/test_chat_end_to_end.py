"""The Phase 1 acceptance path, end to end.

HTTP request -> API key authentication -> use case -> routing policy ->
runtime port -> SSE frames, against a real Postgres.

The runtime itself is a stub. Actual inference needs a GPU and can only be
verified on the Mac Studio, so pretending otherwise here would be dishonest.
Everything between the socket and the port boundary is real.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models import UsageRecordRow
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.entities.user import User
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.config import get_settings
from tests.integration.conftest import reset_schema

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

PEPPER = "test-pepper"


class StubRuntime:
    """Stands in for Ollama. Records whether it was closed on early exit."""

    def __init__(self, chunks: int = 3, prompt_tokens: int = 0) -> None:
        self._chunks = chunks
        self._prompt_tokens = prompt_tokens
        """Carried on the terminal chunk, as a real runtime reports it. Zero by
        default so every case written before prompt tokens existed still
        describes the same request."""

        self.cleaned_up = False
        self.seen_ref: str | None = None
        self.seen_max_tokens: int | None = None
        self.seen_thinking: bool | None = None
        self.seen_messages: Sequence[Message] = ()
        """What actually reached the runtime, which is where grounding shows up:
        the retrieval tests assert on the messages rather than on the answer."""

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
    ) -> AsyncIterator[CompletionChunk]:
        self.seen_ref = ref
        self.seen_max_tokens = max_tokens
        self.seen_thinking = thinking
        self.seen_messages = list(messages)
        try:
            for i in range(self._chunks):
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
            yield CompletionChunk(
                delta="",
                finish_reason="stop",
                token_count=0,
                prompt_tokens=self._prompt_tokens,
            )
        finally:
            self.cleaned_up = True


async def _seed(plaintext_holder: dict) -> None:
    """Create the minimum a request needs: a user, a key, a node, a model,
    and a policy that routes the `chat` capability at it."""
    # Alembic's env.py drives migrations with `asyncio.run`, which cannot be
    # called from inside a running loop, so the rebuild happens on a worker
    # thread. Building the schema from the ORM instead would leave the
    # migrations untested, which is what this replaced.
    await asyncio.to_thread(reset_schema, TEST_DATABASE_URL or "")
    engine = create_async_engine(TEST_DATABASE_URL or "")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await PostgresUserRepository.unscoped(session).save(
            User(id="u1", login="owner@example.com", display_name="Owner", role=Role.ADMIN)
        )

        issued = ApiKeyService(peppers=(PEPPER.encode(),)).issue()
        plaintext_holder["token"] = issued.plaintext
        await PostgresApiKeyRepository.unscoped(session).save(
            ApiKey(
                id=str(uuid.uuid4()),
                key_id=issued.key_id,
                digest=issued.digest,
                name="e2e",
                owner_id="u1",
                # Broad on purpose. The gateway now refuses a capability the
                # key was not issued for, so a fixture restricted to `chat`
                # could not reach the "nothing serves this" path at all: the
                # refusal would arrive first and hide it. Tests about the
                # capability list mint their own narrow keys.
                scopes=frozenset({"chat", "code", "vision"}),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )

        await PostgresNodeRepository(session).save(
            Node(
                id="n1",
                name="mac-studio",
                address="100.64.0.1",
                status=NodeStatus.ONLINE,
                total_memory_gb=64.0,
                runtimes=frozenset({RuntimeKind.OLLAMA}),
            )
        )
        await PostgresModelRepository(session).save(
            Model(
                id="m1",
                alias="primary",
                ref="qwen2.5:7b",
                runtime=RuntimeKind.OLLAMA,
                node_id="n1",
                state=ModelState.LOADED,
                capabilities=frozenset({"chat"}),
                resource_profile=ResourceProfile(memory_gb=8.0, context_length=32768),
            )
        )
        # Two capabilities served by the same model, which is what lets a test
        # tell "this key may not ask for that" apart from "nothing serves it".
        for capability in ("chat", "code"):
            await PostgresRoutingPolicyRepository(session).save(
                RoutingPolicy(
                    capability=capability,
                    candidates=(
                        RoutingCandidate(
                            model_alias="primary",
                            priority=100,
                            require=Requirement(
                                node_status=frozenset({NodeStatus.ONLINE}),
                                model_state=frozenset({ModelState.LOADED}),
                            ),
                        ),
                    ),
                )
            )
        await session.commit()
    await engine.dispose()


async def issue_key(**overrides) -> str:
    """Mint an extra key with custom limits, and return its plaintext."""
    engine = create_async_engine(TEST_DATABASE_URL or "")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    issued = ApiKeyService(peppers=(PEPPER.encode(),)).issue()
    async with factory() as session:
        fields = {
            "id": str(uuid.uuid4()),
            "key_id": issued.key_id,
            "digest": issued.digest,
            "name": "extra",
            "owner_id": "u1",
            "scopes": frozenset({"chat"}),
            "expires_at": datetime.now(UTC) + timedelta(days=1),
            **overrides,
        }
        await PostgresApiKeyRepository.unscoped(session).save(ApiKey(**fields))
        await session.commit()
    await engine.dispose()
    return issued.plaintext


async def count_usage() -> int:
    """Counted through a fresh engine, so nothing can be served out of the
    application's own session state."""
    engine = create_async_engine(TEST_DATABASE_URL or "")
    factory = async_sessionmaker(engine)
    async with factory() as session:
        total = await session.scalar(select(func.count()).select_from(UsageRecordRow))
    await engine.dispose()
    return int(total or 0)


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL or "")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("API_KEY_PEPPER", PEPPER)
    # No Redis in the test environment; per-process counting is fine here
    # because each test builds its own app.
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()

    holder: dict = {}
    await _seed(holder)

    from app.infrastructure.main_gateway import create_app

    app = create_app()
    runtime = StubRuntime()

    with TestClient(app) as test_client:
        # Replace the runtime after startup: everything else, including the
        # database and the routing policy, stays real.
        app.state.runtimes = {RuntimeKind.OLLAMA: runtime}
        test_client.headers["Authorization"] = f"Bearer {holder['token']}"
        yield test_client, runtime, holder

    get_settings.cache_clear()


def _sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload == "[DONE]":
            continue
        events.append(json.loads(payload))
    return events


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


# --- regressions for defects found by adversarial review ------------------


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
    assert response.json()["error"]["code"] == "not_authorized"
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


# --- retrieval-augmented generation --------------------------------------


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
