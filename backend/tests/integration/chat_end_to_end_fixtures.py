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
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.entities.user import User
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.config import get_settings
from tests.integration.conftest import reset_schema

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

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
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
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
