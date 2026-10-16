"""Shared knowledge fences and immutable grounding records."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeEpoch:
    epoch: int
    mutations_in_progress: int
    embedding_identity: str | None = None
    index_requires_rebuild: bool = False
    index_rebuilding: bool = False

    @property
    def clean(self) -> bool:
        return self.mutations_in_progress == 0


class KnowledgeEpochPort(Protocol):
    async def read(self, collection_id: str | None) -> KnowledgeEpoch | None: ...

    def mutation(self, collection_id: str) -> AbstractAsyncContextManager[None]:
        """Commit Begin before touching content, and End after publication.

        A crashed/uncertain writer keeps the fence dirty; elapsed time is not
        evidence that a mutation has completed.
        """
        ...

    async def bind_embedding_identity(self, identity: str) -> None: ...


class GroundingRecordStorePort(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def get_first(self, keys: Sequence[str]) -> tuple[str, str] | None:
        """One bounded round trip, returning only the most recent stored chain."""
        ...

    async def set_grounding_if_absent(
        self, bucket: str, key: str, value: str, ttl_seconds: int
    ) -> bool:
        """Atomic SET NX with tenant/global quotas; false also means quota full."""
        ...
