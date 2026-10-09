"""`RuntimeDirectory` and `NODE_AGENT_ENABLED` (PR4a-2 on #24).

Off, nothing changes. On, a runtime is reached only through the selected
node's agent, and every path that still looks one up by kind fails closed.
"""

from __future__ import annotations

import pytest

from app.adapters.http.node_health import RuntimeNodeHealth
from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import RuntimeCapabilityError
from app.domain.ports.model_runtime_port import runtime_for
from app.infrastructure.config import Settings
from app.infrastructure.di.shared import build_runtimes
from app.infrastructure.runtime_directory import RuntimeDirectory

TOKEN = "t" * 40


def _node(agent_url: str | None = "http://node-a:9100") -> Node:
    return Node(
        id="n1",
        name="a",
        address="100.64.0.1",
        status=NodeStatus.ONLINE,
        total_memory_gb=64,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
        agent_url=agent_url,
    )


def _direct() -> dict[RuntimeKind, OllamaAdapter]:
    return {RuntimeKind.OLLAMA: OllamaAdapter(base_url="http://host.docker.internal:11434")}


def test_off_is_exactly_the_by_kind_mapping() -> None:
    direct = _direct()
    directory = RuntimeDirectory(dict(direct))

    assert not directory.agents_enabled
    assert directory[RuntimeKind.OLLAMA] is direct[RuntimeKind.OLLAMA]
    assert runtime_for(directory, _node(), RuntimeKind.OLLAMA) is direct[RuntimeKind.OLLAMA]
    assert runtime_for(directory, None, RuntimeKind.OLLAMA) is direct[RuntimeKind.OLLAMA]


def test_on_reaches_the_selected_nodes_agent_and_reuses_it() -> None:
    directory = RuntimeDirectory(dict(_direct()), agent_token=TOKEN)

    first = runtime_for(directory, _node(), RuntimeKind.OLLAMA)
    again = runtime_for(directory, _node(), RuntimeKind.OLLAMA)
    other = runtime_for(directory, _node("http://node-b:9100"), RuntimeKind.OLLAMA)

    assert isinstance(first, NodeAgentRuntime)
    assert again is first
    assert isinstance(other, NodeAgentRuntime) and other is not first


@pytest.mark.parametrize(
    ("node", "kind"),
    [
        (None, RuntimeKind.OLLAMA),
        (_node(agent_url=None), RuntimeKind.OLLAMA),
        (_node(), RuntimeKind.MLX),
    ],
    ids=["no node", "no agent", "kind without an agent"],
)
def test_on_refuses_what_has_no_agent(node: Node | None, kind: RuntimeKind) -> None:
    directory = RuntimeDirectory(dict(_direct()), agent_token=TOKEN)
    assert runtime_for(directory, node, kind) is None


async def test_on_a_by_kind_lookup_never_sends() -> None:
    """Design R4: a path not yet converted fails closed instead of going
    around the agent."""
    runtime = RuntimeDirectory(dict(_direct()), agent_token=TOKEN)[RuntimeKind.OLLAMA]

    with pytest.raises(RuntimeCapabilityError, match="through its node's agent"):
        async for _ in runtime.generate("qwen2.5:7b", [Message(MessageRole.USER, "hi")]):
            pass
    with pytest.raises(RuntimeCapabilityError):
        await runtime.embed("nomic-embed-text", ["a"])
    with pytest.raises(RuntimeCapabilityError):
        await runtime.load("qwen2.5:7b")
    with pytest.raises(RuntimeCapabilityError):
        await runtime.unload("qwen2.5:7b")
    with pytest.raises(RuntimeCapabilityError):
        runtime.pull("qwen2.5:7b")
    assert await runtime.health() is False
    assert await runtime.residency() is None
    runtime.validate_ref("qwen2.5:7b")  # grammar only, still answered


async def test_on_a_node_without_an_agent_probes_offline() -> None:
    health = RuntimeNodeHealth(RuntimeDirectory(dict(_direct()), agent_token=TOKEN))
    assert await health.probe(_node(agent_url=None)) is NodeStatus.OFFLINE


def test_the_flag_is_off_by_default() -> None:
    directory = build_runtimes(Settings())
    assert not directory.agents_enabled
    assert isinstance(directory[RuntimeKind.OLLAMA], OllamaAdapter)


@pytest.mark.parametrize("token", ["", "short"])
def test_the_flag_without_a_real_token_does_not_start(token: str) -> None:
    settings = Settings(node_agent_enabled=True, node_agent_token=token)
    with pytest.raises(ValueError, match="node_agent_token"):
        build_runtimes(settings)


def test_the_flag_with_a_token_builds_an_agent_directory() -> None:
    directory = build_runtimes(Settings(node_agent_enabled=True, node_agent_token=TOKEN))
    assert directory.agents_enabled
