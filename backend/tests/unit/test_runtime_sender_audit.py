"""PR4b's audit: nothing reaches a runtime except through its node's agent.

The acceptance on #24: "a static audit shows no runtime HTTP outside the
agent". Three properties, each of which a regression would break:

1. **Where a runtime's API is spoken.** Ollama's `/api/...` paths and MLX's
   OpenAI-style paths appear only in the direct adapters and the agent's
   relay. A new module that calls a runtime would have to name one of them.
2. **Who builds a sender.** The direct adapters are constructed only by
   `build_runtimes` (and, as grammar with no address, inside the agent-backed
   adapter); the relay only by the agent's service.
3. **What the gateway and admin hold with agents enabled.** `build_runtimes`
   then gives every by-kind adapter `NO_RUNTIME_URL` and wraps it in a refusal,
   so the process has no address that reaches a runtime, and a model on a node
   without an agent gets no runtime at all.

Host-side scripts (`scripts/runtime-probes`, `scripts/model-eval`) are out of
scope by design: an operator runs them on the runtime host, in a window they
own, and they never run inside a platform container.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import RuntimeCapabilityError
from app.infrastructure.config import Settings
from app.infrastructure.di.shared import build_runtimes
from app.infrastructure.runtime_directory import NO_RUNTIME_URL

APP = Path(__file__).resolve().parents[2] / "app"

RUNTIME_PATH = re.compile(
    r"^/(api/(chat|generate|embed|embeddings|pull|ps|tags|show|version|delete|copy|create|push)"
    r"|v1/(chat/completions|completions|models))\b"
)
SPEAKS_RUNTIME = (
    "adapters/runtime/ollama_adapter/",
    "adapters/runtime/mlx_adapter/",
    "node_agent/relay.py",
)
BUILDERS = {
    "OllamaAdapter": {"infrastructure/di/shared.py", "adapters/runtime/node_agent_adapter.py"},
    "MlxAdapter": {"infrastructure/di/shared.py"},
    "OllamaRelay": {"node_agent/service.py"},
}


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.relative_to(APP).as_posix(), ast.parse(path.read_text()))
        for path in sorted(APP.rglob("*.py"))
    ]


def test_only_the_adapters_and_the_relay_speak_a_runtimes_api() -> None:
    offending = [
        f"{name}:{node.lineno} {node.value!r}"
        for name, tree in _modules()
        if not name.startswith(SPEAKS_RUNTIME)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and RUNTIME_PATH.match(node.value)
        # The gateway's own OpenAI-compatible routes are not a runtime call.
        and not name.startswith("interfaces/")
    ]
    assert offending == []


def test_runtime_senders_are_built_only_where_expected() -> None:
    built: dict[str, set[str]] = {cls: set() for cls in BUILDERS}
    for name, tree in _modules():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in BUILDERS
            ):
                built[node.func.id].add(name)
    assert built == BUILDERS


def _settings(enabled: bool) -> Settings:
    return Settings(  # type: ignore[call-arg]
        node_agent_enabled=enabled,
        node_agent_token="t" * 40 if enabled else "",
        ollama_base_url="http://ollama.example:11434",
        mlx_base_url="http://mlx.example:8080",
    )


def _addresses(runtimes: object) -> set[str]:
    """Every runtime address reachable from the directory's by-kind entries."""
    found: set[str] = set()
    for adapter in runtimes.values():  # type: ignore[attr-defined]
        inner = getattr(adapter, "_grammar", adapter)
        url = getattr(inner, "_base_url", None)
        if url is not None:
            found.add(str(url))
    return found


def test_with_agents_enabled_the_process_holds_no_runtime_address() -> None:
    runtimes = build_runtimes(_settings(True))

    assert runtimes.agents_enabled
    assert _addresses(runtimes) == {NO_RUNTIME_URL}


def test_with_agents_disabled_the_direct_adapters_are_unchanged() -> None:
    runtimes = build_runtimes(_settings(False))

    assert _addresses(runtimes) == {"http://ollama.example:11434", "http://mlx.example:8080"}


async def test_every_by_kind_call_refuses_rather_than_sends() -> None:
    runtimes = build_runtimes(_settings(True))
    ollama = runtimes[RuntimeKind.OLLAMA]

    with pytest.raises(RuntimeCapabilityError):
        await ollama.load("qwen2.5:7b")
    with pytest.raises(RuntimeCapabilityError):
        await ollama.unload("qwen2.5:7b")
    with pytest.raises(RuntimeCapabilityError):
        await ollama.embed("nomic-embed-text", ["x"])
    with pytest.raises(RuntimeCapabilityError):
        ollama.pull("qwen2.5:7b")
    assert await ollama.health() is False
    assert await ollama.residency() is None
    ollama.validate_ref("qwen2.5:7b")  # grammar only, nothing sent


def test_a_node_without_an_agent_gets_no_runtime() -> None:
    runtimes = build_runtimes(_settings(True))
    node = Node(
        id="b",
        name="b",
        address="10.0.0.2",
        status=NodeStatus.ONLINE,
        total_memory_gb=64,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )

    assert runtimes.for_node(node, RuntimeKind.OLLAMA) is None
    assert runtimes.for_node(None, RuntimeKind.OLLAMA) is None
