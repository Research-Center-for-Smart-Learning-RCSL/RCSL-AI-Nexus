"""Turning text into vectors, through the platform's own routing.

An embedding model is a registered model like any other: it has a node, a
memory footprint the budget counts, and a routing policy on the `embedding`
capability that decides which one answers. This resolves that policy the way
`RouteChatRequest` resolves `chat`, so there is exactly one mechanism for
naming a model rather than a second setting that could disagree with the
registry.

It takes no `Actor` and checks no scope, deliberately. Embedding is never
something a caller asks for directly: it happens inside ingestion and inside
retrieval, both of which have already checked a scope of their own. A scope
check here would be a second, weaker gate on an operation that is not an
entry point.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from app.domain.entities.embedding import current_embedding_manifest
from app.domain.entities.model import Model, RuntimeKind
from app.domain.exceptions import NoAvailableModelError
from app.domain.ports.model_runtime_port import ModelRuntimePort, runtime_for
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    RoutingPolicyRepositoryPort,
)
from app.domain.services.routing_service import RoutingService

logger = logging.getLogger(__name__)

EMBEDDING_CAPABILITY = "embedding"

MAX_BATCH = 32
"""Texts per call to the runtime.

One request per passage would spend most of its time in round trips, and one
request for a whole document would hand the runtime a payload whose size is
set by how large a document someone uploaded. Batching bounds both.
"""


def embedding_identity(model: Model) -> str | None:
    """Exact weights and vector-space implementation, never dimension alone.

    A mutable tag without its manifest cannot prove an index-compatible space.
    Conservatively require the same runtime and reference as well as digest.
    """
    if not model.manifest_digest:
        return None
    return json.dumps(
        [model.runtime.value, model.ref, model.manifest_digest], separators=(",", ":")
    )


class TextEmbedderPort(Protocol):
    """What a caller needs from the embedder.

    A Protocol because there are two implementations and one of them is not
    `EmbedTexts`: the detached ingestion task opens a short session for
    `resolve` and holds none afterwards, so it cannot be a class constructed
    with request-session repositories. See infrastructure/jobs.py.

    The split between `resolve` and `embed_with` is what makes that possible.
    `resolve` reads the routing policy, the registry and the node table, so it
    needs a session; `embed_with` talks only to the runtime adapter it was
    handed, so it needs none. A document therefore touches the database once at
    the start of indexing rather than once per batch.
    """

    async def resolve(
        self, *, required_identity: str | None = None
    ) -> tuple[Model, ModelRuntimePort]: ...

    async def embed_with(
        self,
        runtime: ModelRuntimePort,
        texts: Sequence[str],
        ref: str | None = None,
        *,
        expected_identity: str | None = None,
    ) -> list[list[float]]: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbedTexts:
    def __init__(
        self,
        policies: RoutingPolicyRepositoryPort,
        models: ModelRepositoryPort,
        nodes: NodeRepositoryPort,
        runtimes: dict[RuntimeKind, ModelRuntimePort],
        routing: RoutingService,
    ) -> None:
        self._policies = policies
        self._models = models
        self._nodes = nodes
        self._runtimes = runtimes
        self._routing = routing

    async def resolve(
        self, *, required_identity: str | None = None
    ) -> tuple[Model, ModelRuntimePort]:
        """Which model answers `embedding`, and the adapter that can drive it.

        Exposed rather than kept private because the caller needs the model's
        identity as well as its output: the vector store's index is sized for a
        particular model, and re-indexing under a different one is a decision,
        not something to discover from a dimension mismatch.
        """
        policy = await self._policies.get(EMBEDDING_CAPABILITY)
        if policy is None:
            raise NoAvailableModelError(
                detail="no routing policy for capability=embedding; the knowledge "
                "base needs one before a document can be indexed"
            )

        models = {m.alias: m for m in await self._models.list_all()}
        if required_identity is not None:
            # Fail over only to the same index space, even when an unrelated
            # model happens to produce vectors with the same dimension.
            models = {a: m for a, m in models.items() if embedding_identity(m) == required_identity}
        nodes = {n.id: n for n in await self._nodes.list_all()}
        target = self._routing.select(policy, models, nodes)

        # By the selected node, not the kind alone (final spec §1 on #24).
        runtime = runtime_for(self._runtimes, nodes.get(target.node_id), target.runtime)
        if runtime is None:
            raise NoAvailableModelError(detail=f"no adapter for runtime={target.runtime}")
        return target, runtime

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors in the order given, batched.

        No concurrency slot is taken. The slot count is sized for interactive
        generation, and ingestion holding one for the length of a document
        would let a single upload starve the chat path; embedding is short and
        the runtime serialises its own work regardless.
        """
        if not texts:
            return []
        target, runtime = await self.resolve()
        return await self.embed_with(runtime, texts, target.ref)

    async def embed_with(
        self,
        runtime: ModelRuntimePort,
        texts: Sequence[str],
        ref: str | None = None,
        *,
        expected_identity: str | None = None,
        before_batch: Callable[[], Awaitable[None]] | None = None,
    ) -> list[list[float]]:
        """Batched embedding against an already-resolved runtime, so a caller
        that ingests a whole document resolves the policy once rather than once
        per batch.

        `before_batch` runs before every call to the runtime, so a caller that
        must stop between batches (the maintenance hold, #61) can raise there;
        the batches already embedded are discarded with the failure."""
        if ref is None:
            target, runtime = await self.resolve()
            ref = target.ref

        required_manifest = None
        if expected_identity is not None:
            try:
                fields = json.loads(expected_identity)
                if (
                    not isinstance(fields, list)
                    or len(fields) != 3
                    or fields[1] != ref
                    or not isinstance(fields[2], str)
                    or not fields[2]
                ):
                    raise ValueError("invalid embedding identity")
                required_manifest = fields[2]
            except (ValueError, TypeError, IndexError) as exc:
                raise NoAvailableModelError(
                    detail="embedding identity cannot be validated"
                ) from exc
            if not getattr(runtime, "supports_embedding_manifest_pin", False):
                raise NoAvailableModelError(
                    detail="embedding sender cannot validate pinned weights"
                )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            if before_batch is not None:
                await before_batch()
            # Scoped to this async task and reset even on failure/cancellation.
            # The agent receives the expected manifest on every batch, so a
            # mutable tag repinned after resolve cannot silently switch spaces.
            token = current_embedding_manifest.set(required_manifest)
            try:
                produced = await runtime.embed(ref, batch)
            finally:
                current_embedding_manifest.reset(token)
            if len(produced) != len(batch):
                # A silent mismatch would pair passages with the wrong vectors,
                # which is a knowledge base that retrieves confidently and
                # wrongly rather than one that visibly fails.
                raise NoAvailableModelError(
                    detail=f"embedding runtime returned {len(produced)} vectors for "
                    f"{len(batch)} texts"
                )
            vectors.extend(produced)
        return vectors
