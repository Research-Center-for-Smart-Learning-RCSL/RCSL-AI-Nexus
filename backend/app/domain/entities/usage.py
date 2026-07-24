from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
