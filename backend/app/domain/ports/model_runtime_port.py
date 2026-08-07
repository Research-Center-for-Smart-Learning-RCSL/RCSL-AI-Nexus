from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import PullProgress, RuntimeResidency


class ModelRuntimePort(Protocol):
    """A model runtime, e.g. Ollama or vLLM.

    Runtimes run natively on the macOS host rather than in Docker, because
    containers on macOS cannot reach the GPU. Adapters therefore talk to
    something on `host.docker.internal`, not a sibling container.
    """

    def generate(
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
        """Stream completion chunks. Implementations are async generators.

        `tools` are forwarded to the runtime uninterpreted; the platform never
        executes one, and never validates a call against its schema. A runtime
        that cannot call tools raises `RuntimeCapabilityError` when given a
        non-empty list rather than generating without them: a caller whose
        tools were silently dropped receives prose where their agent loop
        expects a call, which fails somewhere far from the cause. That is the
        same judgement `embed` and `unload` make on the MLX adapter.

        `tool_choice` of NONE is honoured everywhere by not sending the tools
        at all. REQUIRED and FUNCTION need the runtime to constrain decoding,
        so an adapter that cannot refuses rather than downgrading to AUTO.

        `sampling` carries only what the caller actually set, so a runtime's own
        defaults stay in force for everything else.

        `context_length` must match what `load` was given for the same model.
        Ollama keys a runner on the options that shape it, so a generate that
        omits it after a load that supplied it starts a *second* runner at the
        model's own maximum — which is the allocation this argument exists to
        avoid, arriving one request later instead of at load.

        `thinking=False` asks a model that deliberates to answer directly. It
        is a per-call argument rather than adapter state because one resident
        copy of a model has to serve both kinds of request: the registry cannot
        hold the same weights twice (`ix_models_node_ref` is unique on node,
        runtime and ref) and the memory budget would count them twice if it
        could. A runtime with no such notion ignores it.

        Only ever expressed as suppression. Ollama refuses `think: true` for a
        model that does not support thinking, so `True` here means "leave the
        model alone", not "ask it to think".

        Declared with `def`, not `async def`. An async generator function is
        called without await and returns the iterator directly; annotating it
        `async def` here would mean "await this to obtain an iterator", which
        no implementation does, and any caller written against that signature
        raises at runtime. This distinction is silent until it breaks, so it
        is spelled out rather than left to convention.

        `AsyncGenerator` rather than `AsyncIterator`, because every consumer
        wraps this in `aclosing()` and only the former promises `aclose()`.
        That promise is the streaming contract: without it a disconnected
        client leaves the runtime generating and the concurrency slot held.
        """
        ...

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for a batch of texts, in the order given.

        On this port rather than a separate `EmbeddingPort` so that an embedding
        model is registered, budgeted and routed exactly like a chat model: one
        registry, one memory budget, and a routing policy on the `embedding`
        capability decides which model answers. A second mechanism for naming a
        model would be a second place for the registry to be wrong.

        A runtime that cannot embed raises `RuntimeCapabilityError` rather than
        returning something. Reporting a plausible vector would poison a
        knowledge base silently, which is the same reasoning that makes the MLX
        adapter refuse `unload` instead of claiming success.
        """
        ...

    def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """Stream download progress. Also an async generator: Ollama's pull
        endpoint returns a stream of NDJSON progress objects, not a single
        response, so a plain POST would report no progress and give no
        reliable completion signal."""
        ...

    def validate_ref(self, ref: str) -> None:
        """Raise `InvalidModelReferenceError` if this runtime cannot accept it.

        On the port rather than as a shared helper, because what a reference
        *is* differs by runtime: Ollama takes `namespace/name:tag` from a
        small set of registries, while MLX takes a HuggingFace repository id
        and vLLM will take a path. A single grammar would have to be the union
        of all of them, which is no grammar at all.

        Called at registration as well as inside every adapter method. The
        adapter's check protects the runtime call; this one stops a reference
        that can never work from being stored, where it would fail much later
        as a download that cannot start.
        """
        ...

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        """Warm the weights, sized to the context the platform will actually use.

        `context_length` is the model's registered `resource_profile`, and it
        is here because a runtime that is told nothing sizes its KV cache for
        the model's *own* declared maximum. Ollama predicted 55.8 GiB for a
        262144-token context on a model this deployment never sends more than
        65536 to, and evicted every other resident model to make room
        (PROGRESS.md 2026-08-07). None means "do not say", which is what a
        runtime with no such control gets.
        """
        ...

    async def unload(self, ref: str) -> None: ...

    async def health(self) -> bool: ...

    async def residency(self) -> RuntimeResidency | None:
        """What the runtime is actually holding, or None if it cannot say.

        The registry's `state` records intent, asserted once at load time; a
        runtime restart, an out-of-band eviction, or the runtime's own idle
        timer all leave that assertion standing while the weights are gone.
        This is the read-back that lets the heartbeat catch the divergence.

        None means "this runtime has no way to answer", not "nothing is
        resident" — mlx_lm.server has no residency endpoint, and for such a
        runtime the platform falls back to trusting intent, which is exactly
        the pre-observation behaviour. An empty `RuntimeResidency` by contrast
        is a positive claim that nothing is loaded.
        """
        ...
