"""The node agent end to end: its app and lifespan on real PostgreSQL, with a
simulated Ollama behind the relay.

Covers the PR4a acceptance items that need no gateway (design revisions on
#24): a repeated op id replays without a second execution, a refusal leaves no
row, an uncertain outcome blocks inference and embeddings alike, and a lost
election session closes the gate.
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

from app.domain.entities.chat import Message, MessageRole
from app.node_agent import service
from app.node_agent.api import create_app
from app.node_agent.dispatch import GateState
from app.node_agent.relay import OllamaRelay
from app.node_agent.settings import AgentSettings
from app.node_agent.wire import (
    EmbeddingRequest,
    Envelope,
    GenerationRequest,
    encode_embedding,
    encode_generation,
)

NODE = "33333333-3333-3333-3333-333333333333"
TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeOllama:
    def __init__(self) -> None:
        self.chats = 0
        self.embeds = 0
        self.truncate = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            self.chats += 1
            lines = [
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
            ]
            if not self.truncate:
                lines.append(
                    {
                        "message": {"role": "assistant", "content": ""},
                        "done": True,
                        "done_reason": "stop",
                        "eval_count": 2,
                        "prompt_eval_count": 11,
                    }
                )
            return httpx.Response(200, content="".join(json.dumps(x) + "\n" for x in lines))
        if request.url.path == "/api/embed":
            self.embeds += 1
            return httpx.Response(200, json={"embeddings": [[0.5, 0.25]], "prompt_eval_count": 2})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.33.2"})
        return httpx.Response(404)


@pytest.fixture
async def client(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    await conn.execute(
        "INSERT INTO nodes (id, name, address, status, total_memory_gb, runtimes) "
        "VALUES ($1, 'node-e', '100.64.0.3', 'online', 64, '[\"ollama\"]')",
        NODE,
    )
    for alias, ref, ctx, caps in (
        ("qwen7b", "qwen2.5:7b", 32768, '["chat"]'),
        ("embedder", "nomic-embed-text", 2048, '["embedding"]'),
    ):
        await conn.execute(
            "INSERT INTO models (id, alias, ref, runtime, node_id, state, capabilities, "
            "memory_gb, context_length) VALUES ($1, $2, $3, 'ollama', $4, 'loaded', $5, 1, $6)",
            f"{alias}-id",
            alias,
            ref,
            NODE,
            caps,
            ctx,
        )
    await conn.close()

    ollama = FakeOllama()
    monkeypatch.setattr(
        service,
        "OllamaRelay",
        lambda base_url, timeout_s: OllamaRelay(
            base_url, timeout_s=timeout_s, transport=httpx.MockTransport(ollama.handle)
        ),
    )
    settings = AgentSettings(
        NODE_AGENT_NODE_ID=NODE,
        agent_database_url=database_url,
        node_agent_token=TOKEN,
        NODE_AGENT_RUNTIME_URL="http://runtime",
        NODE_AGENT_LOCK_DIR=tmp_path / "lock",
        NODE_AGENT_WATCHDOG_SECONDS=0.05,
    )
    (tmp_path / "lock").mkdir()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        agent = app.state.agent
        terminated: list[bool] = []
        agent.terminate = lambda: terminated.append(True)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agent") as http:
            yield {
                "http": http,
                "ollama": ollama,
                "agent": agent,
                "terminated": terminated,
                "dsn": dsn,
            }


def _generation(op_id: str, **changes: Any) -> dict[str, Any]:
    request = GenerationRequest(
        ref="qwen2.5:7b",
        messages=(Message(role=MessageRole.USER, content="hi"),),
        max_tokens=256,
        thinking=False,
        tools=(),
        tool_choice=None,
        sampling=None,
        context_length=32768,
    )
    body = encode_generation(
        request, Envelope(op_id=op_id, request_id="r", payload_hash="v1:h", store_output=True)
    )
    body.update(changes)
    return body


async def _events(response: httpx.Response) -> list[dict[str, Any]]:
    return [json.loads(line) async for line in response.aiter_lines() if line.strip()]


async def test_a_token_is_required(client: dict[str, Any]) -> None:
    response = await client["http"].get("/v1/status")
    assert response.status_code == 401
    wrong = await client["http"].get("/v1/status", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


async def test_an_inference_streams_and_settles_before_its_terminal_event(
    client: dict[str, Any],
) -> None:
    async with client["http"].stream(
        "POST", "/v1/inference", json=_generation("op-1"), headers=AUTH
    ) as response:
        assert response.status_code == 200
        events = await _events(response)

    assert events[0] == {"type": "accepted", "op_id": "op-1"}
    assert [e["type"] for e in events[1:-1]] == ["line", "line", "line"]
    terminal = events[-1]
    assert terminal["type"] == "terminal" and terminal["state"] == "completed"
    assert terminal["terminal"]["eval_count"] == 2
    stored = (await client["http"].get("/v1/attempts/op-1", headers=AUTH)).json()
    assert stored["state"] == "completed" and stored["result"]["content"] == "Hello"


async def test_a_repeated_op_id_replays_without_running_again(client: dict[str, Any]) -> None:
    async with client["http"].stream(
        "POST", "/v1/inference", json=_generation("op-2"), headers=AUTH
    ) as response:
        await _events(response)

    again = await client["http"].post("/v1/inference", json=_generation("op-2"), headers=AUTH)

    assert again.status_code == 200 and again.json()["state"] == "completed"
    assert again.json()["result"]["content"] == "Hello"
    assert client["ollama"].chats == 1, "executed once"


async def test_a_guard_refusal_leaves_no_row(client: dict[str, Any]) -> None:
    response = await client["http"].post(
        "/v1/inference", json=_generation("op-3", context_length=8192), headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["refused"] == "context_length_mismatch"
    absent = await client["http"].get("/v1/attempts/op-3", headers=AUTH)
    assert absent.status_code == 404
    assert client["ollama"].chats == 0


async def test_a_malformed_request_is_a_400(client: dict[str, Any]) -> None:
    response = await client["http"].post(
        "/v1/inference", json=_generation("op-4", max_tokens=None), headers=AUTH
    )
    assert response.status_code == 400


async def test_an_uncertain_outcome_blocks_chat_and_embeddings(client: dict[str, Any]) -> None:
    client["ollama"].truncate = True
    async with client["http"].stream(
        "POST", "/v1/inference", json=_generation("op-5"), headers=AUTH
    ) as response:
        events = await _events(response)
    assert events[-1]["state"] == "outcome_unknown"
    client["ollama"].truncate = False

    chat = await client["http"].post("/v1/inference", json=_generation("op-6"), headers=AUTH)
    embed = await client["http"].post(
        "/v1/embeddings",
        json=encode_embedding(
            EmbeddingRequest(ref="nomic-embed-text", texts=("a",)),
            Envelope(op_id="op-7", request_id=None, payload_hash=None, store_output=False),
        ),
        headers=AUTH,
    )

    assert chat.status_code == 503 and chat.json()["refused"] == "node_blocked"
    assert "Retry-After" in chat.headers
    assert embed.status_code == 503
    assert client["ollama"].chats == 1 and client["ollama"].embeds == 0
    status = (await client["http"].get("/v1/status", headers=AUTH)).json()
    assert status["unknown"] is True and status["gate"] == "blocked"


async def test_an_embedding_batch_returns_its_vectors(client: dict[str, Any]) -> None:
    response = await client["http"].post(
        "/v1/embeddings",
        json=encode_embedding(
            EmbeddingRequest(ref="nomic-embed-text", texts=("a",)),
            Envelope(op_id="op-8", request_id=None, payload_hash=None, store_output=False),
        ),
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "completed"
    assert response.json()["embeddings"] == [[0.5, 0.25]]


async def test_a_lost_election_session_closes_the_gate_and_ends_the_process(
    client: dict[str, Any],
) -> None:
    agent = client["agent"]
    killer = await asyncpg.connect(client["dsn"])
    try:
        await killer.execute("SELECT pg_terminate_backend($1)", agent.elected.backend_pid)
    finally:
        await killer.close()
    for _ in range(100):
        if client["terminated"]:
            break
        await asyncio.sleep(0.02)

    assert client["terminated"] == [True]
    assert agent.dispatcher.state is GateState.LOST
    refused = await client["http"].post("/v1/inference", json=_generation("op-9"), headers=AUTH)
    assert refused.status_code == 503 and refused.json()["refused"] == "node_lost"


async def test_the_terminal_event_says_whether_delivery_was_complete(
    client: dict[str, Any],
) -> None:
    async with client["http"].stream(
        "POST", "/v1/inference", json=_generation("op-d"), headers=AUTH
    ) as response:
        events = await _events(response)

    assert events[-1]["delivery_complete"] is True


async def test_malformed_lengths_are_refused_before_any_work(client: dict[str, Any]) -> None:
    """Review of #33, finding 11: these were 500s."""
    bad_length = await client["http"].post(
        "/v1/inference",
        content=b"{}",
        headers={**AUTH, "content-length": "abc", "content-type": "application/json"},
    )
    long_op = await client["http"].post("/v1/inference", json=_generation("x" * 37), headers=AUTH)

    assert bad_length.status_code == 400
    assert long_op.status_code == 400
    assert client["ollama"].chats == 0


async def test_a_lost_role_ends_the_process_even_when_its_audit_fails(
    client: dict[str, Any],
) -> None:
    """Review of #33, finding 5: the role is usually lost because the database
    went away, which is when the audit write fails; the exit must not depend
    on it."""
    agent = client["agent"]

    async def failing_audit(*args: Any, **kwargs: Any) -> None:
        raise OSError("database unreachable")

    agent.store.audit = failing_audit
    killer = await asyncpg.connect(client["dsn"])
    try:
        await killer.execute("SELECT pg_terminate_backend($1)", agent.elected.backend_pid)
    finally:
        await killer.close()
    for _ in range(100):
        if client["terminated"]:
            break
        await asyncio.sleep(0.02)

    assert client["terminated"] == [True]
    assert agent.dispatcher.state is GateState.LOST
