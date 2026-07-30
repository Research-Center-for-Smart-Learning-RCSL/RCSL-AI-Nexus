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
from datetime import datetime
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

    observed_state: ModelState | None = None
    """What the runtime last reported actually holding, written by the
    heartbeat. `state` above is the platform's intent; the two diverge when
    something moves weights behind the registry's back — a runtime restart, an
    out-of-band eviction, an `ollama run` nobody recorded. None means the
    runtime has not been observed (or cannot be: MLX has no residency
    endpoint), in which case intent is all there is."""

    observed_memory_gb: float | None = None
    """The runtime's own figure for the resident weights, which includes the
    KV cache the declared profile does not. 5.7 GB measured against 4.7 GB of
    weights for a 7B model, so where this exists the memory budget prefers it."""

    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeResidency:
    """One runtime's answer to "what are you actually holding right now".

    `resident` maps a runtime reference to the memory the runtime itself
    reports for it, in GB. `on_disk` is every reference the runtime could load
    without downloading. An adapter reports every spelling it would answer to
    — Ollama lists `name:latest` under the bare name too — so the observer
    matches registry refs by exact lookup and no runtime grammar leaks out of
    the adapter that owns it.
    """

    resident: dict[str, float] = field(default_factory=dict)
    on_disk: frozenset[str] = field(default_factory=frozenset)


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
