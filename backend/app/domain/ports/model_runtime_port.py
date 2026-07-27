from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import PullProgress


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
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream completion chunks. Implementations are async generators.

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

    async def load(self, ref: str) -> None: ...

    async def unload(self, ref: str) -> None: ...

    async def health(self) -> bool: ...
