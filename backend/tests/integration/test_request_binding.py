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

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.repositories import (
    PostgresRequestBindings,
    PostgresUsageRepository,
    PostgresUsageSettlement,
)
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.application.use_cases.route_chat_request.binding import RequestBinder, keyed_request_id
from app.domain.entities.attempt import RequestIdentity
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.usage import UsageRecord
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
        observed: list[UsageRecord] = []
        settlement = PostgresUsageSettlement(
            async_sessionmaker(engine, expire_on_commit=False), observe=observed.append
        )

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
                binder=RequestBinder(bindings, nodes, runtimes, settlement),
            )

        handles.update(
            use_case=use_case,
            bindings=bindings,
            usage=usage,
            settlement=settlement,
            observed=observed,
            engine=engine,
        )
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
    assert len(await _usage(stack)) == 1, "a replay records no usage"
    assert stack["usage"].records == [], "agent-backed usage is settled, not recorded"


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
    assert len(await _usage(stack)) == 2


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


# -- usage, exactly once (design R6, S6, T3, U2, revision 6) -----------------


async def _usage(stack: dict[str, Any]) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(stack["dsn"])
    try:
        return await conn.fetch("SELECT * FROM usage_records ORDER BY at")
    finally:
        await conn.close()


async def _owner(stack: dict[str, Any], sql: str, *args: Any) -> None:
    conn = await asyncpg.connect(stack["dsn"])
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _bound_attempt(stack: dict[str, Any], key: str) -> str:
    """A keyed request bound and run to `done` at the agent, with no gateway
    settling it: the state a gateway that died after the terminal commit
    leaves behind."""
    op_id = str(uuid.uuid4())
    await stack["bindings"].create(
        tenant_id=DEFAULT_TENANT_ID,
        request_id=keyed_request_id(key),
        payload_hash=_payload(key),
        hash_version="v1",
        key_supplied=True,
        billing={
            "actor_id": ACTOR.id,
            "api_key_id": None,
            "tenant_id": DEFAULT_TENANT_ID,
            "capability": "chat",
            "requested_capability": None,
            "model_alias": "qwen7b",
            "model_ref": "qwen2.5:7b",
            "node_id": NODE,
            "started_at": "2026-10-09T00:00:00+00:00",
            "compaction": {"tier": None, "tokens_before": None, "tokens_after": None},
        },
        node_id=NODE,
        op_id=op_id,
    )
    async with stack["http"].stream(
        "POST", "/v1/inference", json=_original(op_id), headers=AUTH
    ) as response:
        await response.aread()
    return op_id


async def test_a_delivered_request_is_billed_once_from_the_runtime(stack: dict[str, Any]) -> None:
    await _ask(stack, _identity("key-u1"))
    await stack["settlement"].sweep()

    [row] = await _usage(stack)
    assert row["attempt_id"] is not None and row["actor_id"] == ACTOR.id
    assert (row["tokens"], row["prompt_tokens"]) == (2, 11)
    assert row["totals_source"] == "runtime_final"
    assert row["prompt_tokens_basis"] == "runtime_final"
    assert row["completed"] is True and row["runtime_completed"] is True
    assert (row["prompt_eval_ms"], row["eval_ms"], row["load_ms"]) == (1234, 45, 7)


async def test_a_settled_row_is_read_back_and_counted_with_its_sources(
    stack: dict[str, Any],
) -> None:
    """The usage read shows where the figures came from, and the metrics see
    the row once, from the writer that inserted it."""
    await _ask(stack, _identity("key-u0"))
    await stack["settlement"].sweep()

    sessions = async_sessionmaker(stack["engine"], expire_on_commit=False)
    async with sessions() as session:
        [read] = await PostgresUsageRepository.unscoped(session).list_records()
    assert (read.totals_source, read.prompt_tokens_basis) == ("runtime_final", "runtime_final")
    assert read.runtime_completed is True and read.attempt_id is not None
    assert (read.prompt_eval_ms, read.eval_ms, read.load_ms) == (1234, 45, 7)

    [counted] = stack["observed"]
    assert (counted.id, counted.attempt_id, counted.tokens) == (read.id, read.attempt_id, 2)
    assert counted.totals_source == "runtime_final" and counted.completed is True
    assert counted.prompt_eval_ms == 1234


async def test_a_sweep_before_the_delivery_flag_is_reconciled_not_duplicated(
    stack: dict[str, Any],
) -> None:
    """Revision 6's ordering: done, the sweeper inserts first, then the
    gateway commits delivery; one row, same attribution and totals, now
    completed."""
    op_id = await _bound_attempt(stack, "key-u2")

    assert await stack["settlement"].sweep() == 1
    [early] = await _usage(stack)
    assert early["completed"] is False

    await stack["settlement"].mark_delivery(op_id, True)
    await stack["settlement"].settle(op_id)
    await stack["settlement"].sweep()

    [row] = await _usage(stack)
    assert row["id"] == early["id"] and row["completed"] is True
    unchanged = ("actor_id", "tenant_id", "attempt_id", "tokens", "prompt_tokens", "totals_source")
    assert all(row[c] == early[c] for c in unchanged)


async def test_a_gateway_dying_after_the_flag_is_recovered_by_the_sweeper(
    stack: dict[str, Any],
) -> None:
    op_id = await _bound_attempt(stack, "key-u3")
    await stack["settlement"].sweep()
    # The gateway commits delivery and dies before reconciling.
    await stack["settlement"].mark_delivery(op_id, True)

    await stack["settlement"].sweep()

    [row] = await _usage(stack)
    assert row["completed"] is True


async def test_a_gateway_dying_before_the_flag_stays_conservative(stack: dict[str, Any]) -> None:
    op_id = await _bound_attempt(stack, "key-u4")

    await stack["settlement"].sweep()
    await stack["settlement"].sweep()

    [row] = await _usage(stack)
    assert row["completed"] is False and row["runtime_completed"] is True
    conn = await asyncpg.connect(stack["dsn"])
    try:
        flag = await conn.fetchval(
            "SELECT client_delivery_complete FROM request_attempts WHERE op_id = $1", op_id
        )
    finally:
        await conn.close()
    assert flag is None, "no delivery evidence is invented"


async def test_racing_writers_leave_one_row(stack: dict[str, Any]) -> None:
    op_id = await _bound_attempt(stack, "key-u5")

    await asyncio.gather(
        stack["settlement"].settle(op_id),
        stack["settlement"].settle(op_id),
        stack["settlement"].sweep(),
    )

    assert len(await _usage(stack)) == 1
    assert len(stack["observed"]) == 1, "only the writer that inserted counts it"


async def test_a_client_that_left_is_billed_once_the_agent_finishes(
    stack: dict[str, Any],
) -> None:
    """S6: no partial row from the disconnecting gateway; the drained totals
    land once, with delivery false and the runtime complete."""
    use_case: RouteChatRequest = stack["use_case"]()
    generation = use_case.execute(ACTOR, "chat", MESSAGES, 256, identity=_identity("key-u6"))
    await anext(generation)
    await generation.aclose()  # the client went away after the first chunk
    await stack["settlement"].sweep()

    [row] = await _usage(stack)
    assert row["completed"] is False and row["runtime_completed"] is True
    assert (row["tokens"], row["totals_source"]) == (2, "runtime_final")
    assert (row["prompt_eval_ms"], row["eval_ms"], row["load_ms"]) == (1234, 45, 7)


async def test_an_unknown_attempt_is_billed_only_once_resolved(stack: dict[str, Any]) -> None:
    """T3/U2: unknown is not billable; once resolved failed, the last
    checkpoint is an estimate, and without one the figure is unavailable."""
    stack["ollama"].truncate = True
    with pytest.raises(StreamInterruptedError):
        await _ask(stack, _identity("key-u7"))
    assert await stack["settlement"].sweep() == 0, "unknown is not billable"

    # The operator's resolution, after the ordered reset (PR4a-1's CLI).
    await _owner(
        stack,
        "UPDATE node_operations SET state = 'failed', resolved_by = 'operator' "
        "WHERE state = 'outcome_unknown'",
    )
    assert await stack["settlement"].sweep() == 1

    [row] = await _usage(stack)
    assert (row["tokens"], row["totals_source"]) == (2, "estimated_from_chunks")
    assert row["prompt_tokens_basis"] in {"exact_counter", "estimate"}
    assert row["runtime_completed"] is False and row["completed"] is False
    assert (row["prompt_eval_ms"], row["eval_ms"], row["load_ms"]) == (None, None, None)
