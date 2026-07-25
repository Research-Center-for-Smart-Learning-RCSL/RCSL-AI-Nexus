from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.tenant import DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class UsageRecord:
    id: str
    actor_id: str
    api_key_id: str | None
    capability: str
    model_alias: str
    tokens: int
    latency_ms: int
    completed: bool
    """False when the stream ended early, e.g. the client disconnected.
    Partial output is still recorded, so usage reflects what the hardware
    actually produced rather than what the caller received."""

    at: datetime

    tenant_id: str = DEFAULT_TENANT_ID
    """The tenant of the actor the usage is attributed to, so per-tenant usage
    reads only see their own. Stamped by the scoped usage repository on write."""
