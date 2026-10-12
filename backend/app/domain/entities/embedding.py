"""The index's required weights revision, scoped to one embedding batch."""

from contextvars import ContextVar

current_embedding_manifest: ContextVar[str | None] = ContextVar(
    "current_embedding_manifest", default=None
)
