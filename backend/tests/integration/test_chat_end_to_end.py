"""The Phase 1 acceptance path, end to end.

HTTP request -> API key authentication -> use case -> routing policy ->
runtime port -> SSE frames, against a real Postgres.

The runtime itself is a stub. Actual inference needs a GPU and can only be
verified on the Mac Studio, so pretending otherwise here would be dishonest.
Everything between the socket and the port boundary is real.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models import Base
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.entities.user import User
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.config import get_settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

PEPPER = "test-pepper"


class StubRuntime:
    """Stands in for Ollama. Records whether it was closed on early exit."""

    def __init__(self, chunks: int = 3) -> None:
        self._chunks = chunks
        self.cleaned_up = False
        self.seen_ref: str | None = None

    async def generate(
        self, ref: str, messages: Sequence[Message]
    ) -> AsyncIterator[CompletionChunk]:
        self.seen_ref = ref
        try:
            for i in range(self._chunks):
                yield CompletionChunk(delta=f"tok{i} ", token_count=1)
            yield CompletionChunk(delta="", finish_reason="stop", token_count=0)
        finally:
            self.cleaned_up = True


async def _seed(plaintext_holder: dict) -> None:
    """Create the minimum a request needs: a user, a key, a node, a model,
    and a policy that routes the `chat` capability at it."""
    engine = create_async_engine(TEST_DATABASE_URL or "")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await PostgresUserRepository(session).save(
            User(id="u1", login="owner@example.com", display_name="Owner", role=Role.ADMIN)
        )

        issued = ApiKeyService(peppers=(PEPPER.encode(),)).issue()
        plaintext_holder["token"] = issued.plaintext
        await PostgresApiKeyRepository(session).save(
            ApiKey(
                id=str(uuid.uuid4()),
                key_id=issued.key_id,
                digest=issued.digest,
                name="e2e",
                owner_id="u1",
                scopes=frozenset({"chat"}),
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
        await PostgresRoutingPolicyRepository(session).save(
            RoutingPolicy(
                capability="chat",
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


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL or "")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("API_KEY_PEPPER", PEPPER)
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
