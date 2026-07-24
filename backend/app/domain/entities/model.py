"""Registry model entity.

Three identifiers exist and are easy to confuse, so they are named explicitly
here (see docs/ARCHITECTURE.md section 2.2):

- `id`     internal UUID, never exposed to API consumers
- `alias`  public name that routing policies bind to; globally unique
- `ref`    runtime-specific identifier passed to the adapter, e.g.
           "qwen2.5-coder:32b"; unique per (runtime, node)

Policies bind to `alias` so that swapping the underlying model does not
require editing every policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ModelState(StrEnum):
    NOT_DOWNLOADED = "not_downloaded"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    ERROR = "error"


class RuntimeKind(StrEnum):
    OLLAMA = "ollama"
    MLX = "mlx"
    VLLM = "vllm"
    LLAMACPP = "llamacpp"


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    memory_gb: float
    context_length: int


@dataclass(frozen=True, slots=True)
class Model:
    id: str
    alias: str
    ref: str
    runtime: RuntimeKind
    node_id: str
    state: ModelState
    capabilities: frozenset[str] = field(default_factory=frozenset)
    resource_profile: ResourceProfile = ResourceProfile(memory_gb=0.0, context_length=0)


@dataclass(frozen=True, slots=True)
class PullProgress:
    """One progress update from a runtime's download stream."""

    status: str
    completed_bytes: int | None = None
    total_bytes: int | None = None

    @property
    def fraction(self) -> float | None:
        if not self.total_bytes or self.completed_bytes is None:
            return None
        return self.completed_bytes / self.total_bytes
