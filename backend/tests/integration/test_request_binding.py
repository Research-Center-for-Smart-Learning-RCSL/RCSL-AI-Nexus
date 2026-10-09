"""`Idempotency-Key` end to end: the chat use case, the request bindings on
real PostgreSQL and a running node agent (PR4a-2 on #24, final spec §5).

Each test counts executions at the simulated runtime, because "never run
twice" is the property everything here exists for.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.repositories import PostgresRequestBindings
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.application.use_cases.route_chat_request.binding import RequestBinder, keyed_request_id
from app.domain.entities.attempt import RequestIdentity
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    StreamInterruptedError,
)
from app.domain.services.routing_service import RoutingService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.runtime_directory import RuntimeDirectory
from app.node_agent.wire import Envelope, GenerationRequest, encode_generation
from app.shared.clock import FixedClock
from tests.integration.node_agent_fixtures import AUTH, NODE, TOKEN, running_agent
from tests.unit.streaming_contract_fixtures import (
    ACTOR,
    FakePolicies,
    FakeRepo,
    RecordingUsage,
)

MESSAGES = [Message(role=MessageRole.USER, content="hi")]
BODY = {"model": "chat", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 256}


class FakeNodes(FakeRepo):
    def __init__(self, nodes: list[Node]) -> None:
        super().__init__(list(nodes))
        self._by_id = {n.id: n for n in nodes}

    async def get(self, node_id: str) -> Node | None:
        return self._by_id.get(node_id)


@pytest.fixture
async def stack(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    async with running_agent(database_url, tmp_path, monkeypatch) as handles:
        engine = create_async_engine(database_url)
        node = Node(
            id=NODE,
            name="node-e",
            address="100.64.0.3",
            status=NodeStatus.ONLINE,
            total_memory_gb=64,
            runtimes=frozenset({RuntimeKind.OLLAMA}),
            agent_url="http://agent",
        )
        model = Model(
            id="qwen7b-id",
            alias="qwen7b",
            ref="qwen2.5:7b",
            runtime=RuntimeKind.OLLAMA,
            node_id=NODE,
            state=ModelState.LOADED,
            capabilities=frozenset({"chat"}),
            resource_profile=ResourceProfile(memory_gb=1.0, context_length=32768),
        )
        policies = FakePolicies(
            RoutingPolicy(capability="chat", candidates=(RoutingCandidate("qwen7b", 100),))
        )
        runtimes = RuntimeDirectory(
            {}, agent_token=TOKEN, timeout_s=30, transport=httpx.ASGITransport(app=handles["app"])
        )
        nodes = FakeNodes([node])
        bindings = PostgresRequestBindings(async_sessionmaker(engine, expire_on_commit=False))
        usage = RecordingUsage()

        def use_case() -> RouteChatRequest:
            return RouteChatRequest(
                policies=policies,
                capabilities=ListCapabilities(policies=policies, authz=RoleAuthorization()),
                models=FakeRepo([model]),
                nodes=nodes,
                usage=usage,
                runtimes=runtimes,
                routing=RoutingService(),
                concurrency=SemaphoreConcurrencyLimiter(4),
                authz=RoleAuthorization(),
                clock=FixedClock(datetime(2026, 10, 9, tzinfo=UTC)),
                max_tokens_ceiling=1000,
                binder=RequestBinder(bindings, nodes, runtimes),
            )

        handles.update(use_case=use_case, bindings=bindings, usage=usage)
        try:
            yield handles
        finally:
            await engine.dispose()


def _identity(key: str | None, **changes: Any) -> RequestIdentity:
    return RequestIdentity(key=key, shape="chat.completions", body={**BODY, **changes})


async def _ask(stack: dict[str, Any], identity: RequestIdentity) -> list[CompletionChunk]:
    """What the HTTP layer does: the repeat check first, then the use case."""
    use_case: RouteChatRequest = stack["use_case"]()
    generation = await use_case.repeat(ACTOR, "chat", identity)
    if generation is None:
        generation = use_case.execute(ACTOR, "chat", MESSAGES, 256, identity=identity)
    async with aclosing(generation) as stream:
        return [chunk async for chunk in stream]


def _text(chunks: list[CompletionChunk]) -> str:
    return "".join(c.delta for c in chunks)


async def test_a_repeated_key_replays_and_runs_once(stack: dict[str, Any]) -> None:
    first = await _ask(stack, _identity("key-1"))
    again = await _ask(stack, _identity("key-1"))

    assert _text(again) == _text(first) == "Hello"
    assert len(again) == 1, "decision Q3: one chunk"
    assert again[0].finish_reason == "stop" and again[0].prompt_tokens == 11
    assert stack["ollama"].chats == 1
    assert len(stack["usage"].records) == 1, "a replay records no usage"


async def test_the_same_key_for_a_different_request_is_refused(stack: dict[str, Any]) -> None:
    await _ask(stack, _identity("key-2"))
    with pytest.raises(IdempotencyKeyReusedError):
        await _ask(stack, _identity("key-2", max_tokens=128))
    assert stack["ollama"].chats == 1


async def test_a_field_the_client_omitted_is_not_its_default() -> None:
    from app.application.use_cases.route_chat_request.binding import payload_hash

    assert payload_hash(_identity("k")) != payload_hash(_identity("k", stream=False))


async def test_an_unknown_outcome_is_never_run_again(stack: dict[str, Any]) -> None:
    stack["ollama"].truncate = True
    with pytest.raises(StreamInterruptedError):
        await _ask(stack, _identity("key-3"))
    stack["ollama"].truncate = False

    with pytest.raises(IdempotencyInProgressError):
        await _ask(stack, _identity("key-3"))
    assert stack["ollama"].chats == 1


async def test_a_binding_whose_forward_was_lost_moves_only_after_a_tombstone(
    stack: dict[str, Any],
) -> None:
    """Design R6: bound, absent at the agent. The retry cancels the old op id
    first, so the late original can only observe the tombstone."""
    lost = str(uuid.uuid4())
    await stack["bindings"].create(
        tenant_id=DEFAULT_TENANT_ID,
        request_id=keyed_request_id("key-4"),
        payload_hash=_payload("key-4"),
        hash_version="v1",
        key_supplied=True,
        billing={"model_ref": "qwen2.5:7b"},
        node_id=NODE,
        op_id=lost,
    )

    retried = await _ask(stack, _identity("key-4"))
    late = await stack["http"].post("/v1/inference", json=_original(lost), headers=AUTH)

    assert _text(retried) == "Hello"
    assert late.json()["state"] == "cancelled_unsent"
    assert stack["ollama"].chats == 1
    bound = await stack["bindings"].lookup(DEFAULT_TENANT_ID, keyed_request_id("key-4"))
    assert bound is not None and bound.seq == 2 and bound.op_id != lost


async def test_concurrent_copies_of_one_key_run_once(stack: dict[str, Any]) -> None:
    results = await asyncio.gather(
        *(_ask(stack, _identity("key-5")) for _ in range(3)), return_exceptions=True
    )

    ran = [r for r in results if isinstance(r, list)]
    refused = [r for r in results if isinstance(r, IdempotencyInProgressError)]
    assert len(ran) + len(refused) == 3, results
    assert ran, "one copy runs"
    assert all(_text(r) == "Hello" for r in ran)
    assert stack["ollama"].chats == 1


async def test_requests_without_a_key_are_bound_and_run_each_time(stack: dict[str, Any]) -> None:
    await _ask(stack, _identity(None))
    await _ask(stack, _identity(None))

    assert stack["ollama"].chats == 2
    assert len(stack["usage"].records) == 2


def _payload(key: str) -> str:
    from app.application.use_cases.route_chat_request.binding import payload_hash

    return payload_hash(_identity(key))


def _original(op_id: str) -> dict[str, Any]:
    return encode_generation(
        GenerationRequest(
            ref="qwen2.5:7b",
            messages=tuple(MESSAGES),
            max_tokens=256,
            thinking=True,
            tools=(),
            tool_choice=None,
            sampling=None,
            context_length=32768,
        ),
        Envelope(op_id=op_id, request_id="k:key-4", payload_hash=None, store_output=True),
    )
