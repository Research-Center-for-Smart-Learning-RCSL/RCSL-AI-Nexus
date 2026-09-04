from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.entities.tenant import DEFAULT_TENANT_ID

BucketUnit = Literal["hour", "day"]
"""The granularity a usage aggregation groups by. A closed set because it
reaches `date_trunc(unit, ...)`; the use case chooses it from the window."""


@dataclass(frozen=True, slots=True)
class UsageBucket:
    """One time bucket of usage for one capability, as the repository aggregates
    it. The use case folds these into per-bucket totals and per-capability
    series for the analytics charts."""

    bucket_start: datetime
    capability: str
    requests: int
    tokens: int


@dataclass(frozen=True, slots=True)
class UsageRecord:
    id: str
    actor_id: str
    api_key_id: str | None
    capability: str
    model_alias: str
    tokens: int
    """Tokens generated. Kept meaning exactly that when `prompt_tokens` was
    added, so rows written before 2026-08-04 stay true rather than being
    reinterpreted as totals they never held."""

    latency_ms: int
    completed: bool
    """False when the stream ended early, e.g. the client disconnected.
    Partial output is still recorded, so usage reflects what the hardware
    actually produced rather than what the caller received."""

    at: datetime

    tenant_id: str = DEFAULT_TENANT_ID
    """The tenant of the actor the usage is attributed to, so per-tenant usage
    reads only see their own. Stamped by the scoped usage repository on write."""

    requested_capability: str | None = None
    """What the caller actually put in `model`, when it is not `capability`.

    Null on every row where the two agree, which is every row this platform
    wrote before keys could carry a `default_capability` and almost every row
    since. Null therefore means "asked for what it got" rather than "unknown",
    and no existing row is reinterpreted by the column arriving.

    It exists because the substitution has to stay legible after the fact. A
    key with a default no longer produces the `capability_not_issued` refusal
    that tells an integrator their client is sending a model name — that is the
    whole point of the setting — so without this the evidence would live only
    in a response header the caller may not read and a log line that rotates.
    Here it outlives both, and "which of these requests asked for something
    else, and what?" is a query rather than an investigation.
    """

    compaction_tier: int | None = None
    """Which tier of compaction was applied, or None when no compaction
    happened. 0 = tool definitions, 1 = old tool results, 2 = summarisation."""

    tokens_before_compaction: int | None = None
    tokens_after_compaction: int | None = None

    prompt_tokens: int = 0
    """Tokens read. Zero on every row written before 2026-08-04, and on any
    runtime that does not report the figure.

    Quota and every usage total sum this alongside `tokens`, because the
    caller asked the hardware to do both halves of the work. Charging for
    output alone meant a context-filling prompt cost nothing, on a machine
    where prompt evaluation is most of the wait."""
