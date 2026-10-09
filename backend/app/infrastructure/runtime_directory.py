"""Which runtime adapter serves a kind **on a given node** (PR4a-2 on #24).

Final spec §1: routing selects a node, and the adapter must then be the one
that reaches that node. Looking it up by kind alone sends to whichever host
the kind's one adapter points at. `RuntimeDirectory` answers `for_node`, which
`runtime_for` asks first.

Two modes, chosen by `NODE_AGENT_ENABLED`:

- **Off (the default).** Exactly what the platform did before: one direct
  adapter per kind, and `for_node` answers by kind. Nothing changes.
- **On.** Every Ollama call goes through the selected node's agent, the only
  sender to its runtime (architecture (b2')). A node without an `agent_url`
  gets no runtime, so the call is refused rather than sent around the agent,
  and the by-kind entries are replaced with adapters that refuse to send:
  any path still looking a runtime up by kind fails closed instead of
  reaching a runtime directly. Turning this on before PR4b's audit of every
  sender is therefore safe in the one sense that matters: whatever has not
  been converted stops working instead of bypassing the agent (design R4).

Every runtime caller resolves by node since PR4b: generation, Tier 2,
embeddings, `/readyz`, the residency sweep, node health, download and the
registry's load and unload. The by-kind entries are then only grammar, and are
built without the runtime's address (`NO_RUNTIME_URL`); the audit in
`tests/unit/test_runtime_sender_audit.py` holds both properties.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

import httpx

from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import PullProgress, RuntimeKind, RuntimeResidency
from app.domain.entities.node import Node
from app.domain.exceptions import RuntimeCapabilityError
from app.domain.ports.model_runtime_port import ModelRuntimePort

MIN_AGENT_TOKEN_LENGTH = 32
"""The agent's own minimum (`AgentSettings.token`)."""

AGENT_KINDS = frozenset({RuntimeKind.OLLAMA})
"""The runtimes a node agent fronts. MLX has no agent yet, so with the flag on
it is refused like any other direct sender."""

NO_RUNTIME_URL = "http://no-runtime.invalid"
"""What a by-kind adapter is built with while agents are enabled: `.invalid`
never resolves (RFC 6761), so even a path that slipped past the refusals
could not reach a runtime."""

_BYPASS = "node agents are enabled; a runtime is reached only through its node's agent"


class RuntimeDirectory(dict[RuntimeKind, ModelRuntimePort]):
    """The runtimes this process may call, by kind and by node.

    A dict so every composition and test that passes a plain mapping keeps
    working; `for_node` is what makes it per node.
    """

    def __init__(
        self,
        direct: dict[RuntimeKind, ModelRuntimePort],
        *,
        agent_token: str | None = None,
        timeout_s: float = 1500.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            direct
            if agent_token is None
            else {kind: _Refusing(kind, adapter) for kind, adapter in direct.items()}
        )
        self._token = agent_token
        self._timeout_s = timeout_s
        self._transport = transport
        """For tests: reach an in-process agent instead of the network."""
        self._agents: dict[str, NodeAgentRuntime] = {}

    @property
    def agents_enabled(self) -> bool:
        return self._token is not None

    def for_node(self, node: Node | None, kind: RuntimeKind) -> ModelRuntimePort | None:
        if self._token is None:
            return self.get(kind)
        if node is None or not node.agent_url or kind not in AGENT_KINDS:
            return None
        agent = self._agents.get(node.agent_url)
        if agent is None:
            agent = NodeAgentRuntime(
                node.agent_url, self._token, timeout_s=self._timeout_s, transport=self._transport
            )
            self._agents[node.agent_url] = agent
        return agent


class _Refusing:
    """A by-kind entry while agents are enabled: it validates references,
    which is grammar and sends nothing, and refuses everything that would
    reach a runtime."""

    def __init__(self, kind: RuntimeKind, grammar: ModelRuntimePort) -> None:
        self._kind = kind
        self._grammar = grammar

    def _refusal(self, what: str) -> RuntimeCapabilityError:
        return RuntimeCapabilityError(detail=f"{self._kind.value} {what}: {_BYPASS}")

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
    ) -> AsyncGenerator[CompletionChunk, None]:
        raise self._refusal("generate")
        yield  # pragma: no cover - makes this an async generator

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        raise self._refusal("embed")

    def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        raise self._refusal("pull")

    def validate_ref(self, ref: str) -> None:
        self._grammar.validate_ref(ref)

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        raise self._refusal("load")

    async def unload(self, ref: str) -> None:
        raise self._refusal("unload")

    async def health(self) -> bool:
        return False

    async def residency(self) -> RuntimeResidency | None:
        """Not observed, which the residency sweep writes back as unobserved
        rather than as absent."""
        return None
