"""A running node agent on real PostgreSQL with a simulated Ollama behind it.

Shared by the agent's API tests and the gateway-side adapter tests, so both
exercise the same agent the same way.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest

from app.node_agent import service
from app.node_agent.api import create_app
from app.node_agent.relay import OllamaRelay
from app.node_agent.settings import AgentSettings

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


@asynccontextmanager
async def running_agent(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    """Start the agent (lifespan included) and yield its handles; a context
    manager rather than a fixture so each test module wraps it its own way."""
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
        # Explicitly none: the settings also read the environment, and a shell
        # with `OLLAMA_MODELS_PATH` set for the real-weight tests would point
        # this agent's guard at the host's model store.
        OLLAMA_MODELS_PATH=None,
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
                "app": app,
                "ollama": ollama,
                "agent": agent,
                "terminated": terminated,
                "dsn": dsn,
            }
