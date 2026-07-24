from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import PullProgress


class ModelRuntimePort(Protocol):
    """A model runtime, e.g. Ollama or vLLM.

    Runtimes run natively on the macOS host rather than in Docker, because
    containers on macOS cannot reach the GPU. Adapters therefore talk to
    something on `host.docker.internal`, not a sibling container.
    """

    def generate(self, ref: str, messages: Sequence[Message]) -> AsyncIterator[CompletionChunk]:
        """Stream completion chunks. Implementations are async generators.

        Declared with `def`, not `async def`. An async generator function is
        called without await and returns the iterator directly; annotating it
        `async def` here would mean "await this to obtain an iterator", which
        no implementation does, and any caller written against that signature
        raises at runtime. This distinction is silent until it breaks, so it
        is spelled out rather than left to convention.
        """
        ...

    def pull(self, ref: str) -> AsyncIterator[PullProgress]:
        """Stream download progress. Also an async generator: Ollama's pull
        endpoint returns a stream of NDJSON progress objects, not a single
        response, so a plain POST would report no progress and give no
        reliable completion signal."""
        ...

    async def load(self, ref: str) -> None: ...

    async def unload(self, ref: str) -> None: ...

    async def health(self) -> bool: ...
