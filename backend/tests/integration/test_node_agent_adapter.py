"""The gateway-side adapter against a real running agent (PR4a-2 on #24).

The adapter speaks to the agent's ASGI app directly, so these exercise the
wire, the agent's checks and the adapter's decoding together.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import PostgresRoutingPolicyRepository
from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.domain.entities.attempt import AttemptIdentity, current_attempt
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
from app.domain.entities.model import RuntimeKind
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import (
    ManifestPinRefusedError,
    NoAvailableModelError,
    RuntimeCapabilityError,
    ServerOverloadedError,
    StreamInterruptedError,
)
from app.infrastructure.availability import read_availability
from app.node_agent.dispatch import GateState
from tests.integration.node_agent_fixtures import NODE, TOKEN, running_agent

MESSAGES = [Message(role=MessageRole.USER, content="hi")]


@pytest.fixture
async def agent(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    async with running_agent(database_url, tmp_path, monkeypatch) as handles:
        handles["runtime"] = NodeAgentRuntime(
            "http://agent",
            TOKEN,
            timeout_s=30,
            transport=httpx.ASGITransport(app=handles["app"]),
        )
        yield handles


async def _generate(runtime: NodeAgentRuntime) -> list[CompletionChunk]:
    return [
        chunk
        async for chunk in runtime.generate(
            "qwen2.5:7b", MESSAGES, max_tokens=256, context_length=32768
        )
    ]


def _keyed(op_id: str) -> AttemptIdentity:
    return AttemptIdentity(op_id=op_id, request_id="key-1", payload_hash="v1:h", store_output=True)


async def test_a_generation_decodes_like_the_direct_adapter(agent: dict[str, Any]) -> None:
    chunks = await _generate(agent["runtime"])

    assert "".join(c.delta for c in chunks) == "Hello"
    assert chunks[-1].finish_reason == "stop"
    assert sum(c.token_count for c in chunks) == 2
    assert chunks[-1].prompt_tokens == 11


async def test_a_repeated_attempt_replays_its_result_and_runs_once(
    agent: dict[str, Any],
) -> None:
    """Final spec §10, PR4a: a completed attempt followed by a retry replays
    the stored result, with an execution count of 1."""
    token = current_attempt.set(_keyed("op-keyed"))
    try:
        first = await _generate(agent["runtime"])
        again = await _generate(agent["runtime"])
    finally:
        current_attempt.reset(token)

    assert len(again) == 1, "decision Q3: one chunk"
    assert again[0].delta == "".join(c.delta for c in first)
    assert again[0].finish_reason == first[-1].finish_reason
    assert again[0].prompt_tokens == 11
    assert agent["ollama"].chats == 1


async def test_unbound_calls_are_separate_attempts(agent: dict[str, Any]) -> None:
    await _generate(agent["runtime"])
    await _generate(agent["runtime"])

    assert agent["ollama"].chats == 2


async def test_a_completed_attempt_without_a_stored_result_is_not_run_again(
    agent: dict[str, Any],
) -> None:
    """Decision Q2: without a key nothing is stored, and a lost acknowledgement
    is reported, never re-executed."""
    unkeyed = AttemptIdentity(
        op_id="op-plain", request_id=None, payload_hash=None, store_output=False
    )
    token = current_attempt.set(unkeyed)
    try:
        await _generate(agent["runtime"])
        with pytest.raises(StreamInterruptedError, match="not retained"):
            await _generate(agent["runtime"])
    finally:
        current_attempt.reset(token)
    assert agent["ollama"].chats == 1


async def test_an_uncertain_outcome_interrupts_and_then_blocks(agent: dict[str, Any]) -> None:
    agent["ollama"].truncate = True
    with pytest.raises(StreamInterruptedError):
        await _generate(agent["runtime"])
    agent["ollama"].truncate = False

    with pytest.raises(ServerOverloadedError) as refused:
        await _generate(agent["runtime"])
    assert refused.value.retry_after_seconds == 60
    with pytest.raises(ServerOverloadedError):
        await agent["runtime"].embed("nomic-embed-text", ["a"])
    assert agent["ollama"].chats == 1 and agent["ollama"].embeds == 0


async def test_embeddings_return_vectors(agent: dict[str, Any]) -> None:
    assert await agent["runtime"].embed("nomic-embed-text", ["a"]) == [[0.5, 0.25]]


async def test_a_repeated_embedding_attempt_replays_its_stored_vectors(
    agent: dict[str, Any],
) -> None:
    """Review of #33's branch: a replayed batch's vectors sit under `result`,
    and the adapter looked only at the top level."""
    token = current_attempt.set(_keyed("op-embed"))
    try:
        first = await agent["runtime"].embed("nomic-embed-text", ["a"])
        again = await agent["runtime"].embed("nomic-embed-text", ["a"])
    finally:
        current_attempt.reset(token)

    assert again == first == [[0.5, 0.25]]
    assert agent["ollama"].embeds == 1


async def test_load_and_unload_go_through_the_agent_with_the_registered_context(
    agent: dict[str, Any],
) -> None:
    runtime = agent["runtime"]
    await runtime.load("qwen2.5:7b", context_length=32768)
    await runtime.unload("qwen2.5:7b")

    sent = agent["ollama"].lifecycle
    assert sent[0]["options"] == {"num_ctx": 32768} and sent[0]["keep_alive"] != 0
    assert sent[1]["keep_alive"] == 0 and "options" not in sent[1]
    kinds = await _rows(agent, "SELECT kind, state FROM node_operations ORDER BY submitted_at")
    assert kinds == [("load", "completed"), ("unload", "completed")]


async def test_a_load_sized_otherwise_than_registered_is_refused(agent: dict[str, Any]) -> None:
    with pytest.raises(RuntimeCapabilityError):
        await agent["runtime"].load("qwen2.5:7b", context_length=4096)
    assert agent["ollama"].lifecycle == []


async def test_a_model_not_on_this_node_is_refused(agent: dict[str, Any]) -> None:
    with pytest.raises(RuntimeCapabilityError):
        await agent["runtime"].unload("gemma4:31b-it-q8_0")


async def test_a_pull_streams_progress_and_repins_before_serving(agent: dict[str, Any]) -> None:
    progress = [p async for p in agent["runtime"].pull("qwen2.5:7b")]

    assert [p.status for p in progress] == ["pulling manifest", "downloading", "success"]
    assert progress[1].completed_bytes == 5 and progress[1].total_bytes == 10
    pin = await _rows(agent, "SELECT manifest_digest FROM models WHERE ref = 'qwen2.5:7b'")
    assert pin == [("b" * 64,)], "the pin names what the runtime now serves"
    audit = await _rows(agent, "SELECT event FROM node_operation_audit WHERE event = 'repin'")
    assert audit == [("repin",)]
    assert await agent["runtime"].health() is True, "the node serves again"


async def _serving(runtime: NodeAgentRuntime) -> bool:
    """The gate reopens as the operation's task ends, just after its answer."""
    for _ in range(50):
        if await runtime.health():
            return True
        await asyncio.sleep(0.1)
    return False


async def _stranded_pin(agent: dict[str, Any]) -> None:
    """The state a pull leaves when its own re-pin did not happen (#68 §3):
    new weights served, the old pin standing."""
    conn = await asyncpg.connect(agent["dsn"])
    try:
        await conn.execute(
            "UPDATE models SET manifest_digest = $1 WHERE ref = 'qwen2.5:7b'", "a" * 64
        )
    finally:
        await conn.close()
    agent["ollama"].digest = "b" * 64


async def test_an_operator_repin_unstrands_a_model_its_pull_left_refused(
    agent: dict[str, Any],
) -> None:
    runtime = agent["runtime"]
    await _stranded_pin(agent)
    with pytest.raises(RuntimeCapabilityError):
        await runtime.load("qwen2.5:7b", context_length=32768)

    await runtime.repin("qwen2.5:7b", "b" * 64)

    pin = await _rows(agent, "SELECT manifest_digest FROM models WHERE ref = 'qwen2.5:7b'")
    assert pin == [("b" * 64,)]
    ops = await _rows(agent, "SELECT kind, state FROM node_operations WHERE kind = 'repin'")
    assert ops == [("repin", "completed")]
    audit = await _rows(
        agent, "SELECT detail->>'by' FROM node_operation_audit WHERE event = 'repin'"
    )
    assert audit == [("operator",)]
    await runtime.load("qwen2.5:7b", context_length=32768)


async def test_a_repin_of_weights_that_are_not_served_changes_nothing(
    agent: dict[str, Any],
) -> None:
    runtime = agent["runtime"]
    await _stranded_pin(agent)

    with pytest.raises(ManifestPinRefusedError) as refused:
        await runtime.repin("qwen2.5:7b", "c" * 64)

    assert (refused.value.reason, refused.value.served) == ("digest_mismatch", "b" * 64)
    pin = await _rows(agent, "SELECT manifest_digest FROM models WHERE ref = 'qwen2.5:7b'")
    assert pin == [("a" * 64,)], "the old pin stands: closed, as after the failed pull"
    ops = await _rows(agent, "SELECT state, reason FROM node_operations WHERE kind = 'repin'")
    assert ops == [("failed", "digest_mismatch")]
    assert await _serving(runtime), "a refused repin does not block the node"
    assert agent["ollama"].lifecycle == [], "nothing was sent to the runtime"


async def test_a_repin_of_a_model_not_on_this_node_is_refused(agent: dict[str, Any]) -> None:
    with pytest.raises(RuntimeCapabilityError):
        await agent["runtime"].repin("gemma4:31b-it-q8_0", "b" * 64)
    assert await _rows(agent, "SELECT kind FROM node_operations") == []


async def test_residency_is_read_through_the_agent(agent: dict[str, Any]) -> None:
    observed = await agent["runtime"].residency()

    assert observed is not None
    assert observed.resident["qwen2.5:7b"] == 5.0
    assert "nomic-embed-text" in observed.on_disk


async def test_a_blocked_node_refuses_lifecycle_but_still_reports_residency(
    agent: dict[str, Any],
) -> None:
    agent["ollama"].truncate = True
    with pytest.raises(StreamInterruptedError):
        await _generate(agent["runtime"])

    with pytest.raises(ServerOverloadedError):
        await agent["runtime"].load("qwen2.5:7b", context_length=32768)
    assert agent["ollama"].lifecycle == []
    assert await agent["runtime"].residency() is not None


@pytest.mark.parametrize("kind", ["load", "unload", "pull"])
async def test_uncertain_lifecycle_is_durable_blocks_dispatch_and_reports_outage(
    agent: dict[str, Any], kind: str
) -> None:
    runtime = agent["runtime"]
    agent["ollama"].uncertain_lifecycle = True
    with pytest.raises(StreamInterruptedError):
        if kind == "load":
            await runtime.load("qwen2.5:7b", context_length=32768)
        elif kind == "unload":
            await runtime.unload("qwen2.5:7b")
        else:
            _ = [p async for p in runtime.pull("qwen2.5:7b")]
    rows = await _rows(agent, "SELECT kind, state, terminal FROM node_operations")
    assert rows == [(kind, "outcome_unknown", None)]
    pin = await _rows(agent, "SELECT manifest_digest FROM models WHERE alias = 'qwen7b'")
    if kind == "pull":
        assert pin == [(None,)], "an incomplete pull cannot repin potentially changed weights"
    agent["ollama"].uncertain_lifecycle = False
    for send in (
        lambda: _generate(runtime),
        lambda: runtime.embed("nomic-embed-text", ["a"]),
        lambda: runtime.load("qwen2.5:7b", context_length=32768),
        lambda: runtime.unload("qwen2.5:7b"),
    ):
        with pytest.raises(ServerOverloadedError) as refused:
            await send()
        assert refused.value.retry_after_seconds == 60
    with pytest.raises(ServerOverloadedError):
        _ = [p async for p in runtime.pull("qwen2.5:7b")]
    assert agent["ollama"].chats == agent["ollama"].embeds == 0
    assert len(agent["ollama"].lifecycle) == (0 if kind == "pull" else 1)
    assert await runtime.residency() is not None, "fresh residency never resolves remote work"
    assert await agent["agent"].dispatcher.reopen() is not GateState.SERVING

    # With no inference traffic, committed evidence still drives #50's gauges
    # and unavailable-capability alert. Even a seven-day-old operation blocks.
    engine = create_async_engine(agent["dsn"].replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                text("UPDATE models SET observed_state = 'loaded', observed_at = clock_timestamp()")
            )
            await session.execute(
                text("UPDATE node_operations SET submitted_at = now() - interval '7 days'")
            )
            await PostgresRoutingPolicyRepository(session).save(
                RoutingPolicy("chat", (RoutingCandidate("qwen7b", 100),))
            )
            await session.commit()
            snapshot = await read_availability(session, {RuntimeKind.OLLAMA: runtime})
            assert snapshot.unresolved == {NODE: 1}
            chat = next(c for c in snapshot.capabilities if c.capability == "chat")
            assert not chat.available and chat.reasons == ("node_operation_unresolved",)
    finally:
        await engine.dispose()


async def _rows(agent: dict[str, Any], sql: str) -> list[tuple[Any, ...]]:
    conn = await asyncpg.connect(agent["dsn"])
    try:
        return [tuple(r) for r in await conn.fetch(sql)]
    finally:
        await conn.close()


async def test_health_reports_the_agents_gate(agent: dict[str, Any]) -> None:
    assert await agent["runtime"].health() is True


async def test_an_unreachable_agent_is_retried_once_with_the_same_op_id() -> None:
    seen: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["op_id"])
        raise httpx.ConnectError("refused")

    runtime = NodeAgentRuntime(
        "http://agent", TOKEN, timeout_s=5, transport=httpx.MockTransport(refuse)
    )
    token = current_attempt.set(_keyed("op-same"))
    try:
        with pytest.raises(NoAvailableModelError, match="unreachable"):
            await _generate(runtime)
    finally:
        current_attempt.reset(token)

    assert seen == ["op-same", "op-same"]
