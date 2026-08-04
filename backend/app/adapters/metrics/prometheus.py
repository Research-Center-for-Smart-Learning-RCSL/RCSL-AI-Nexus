"""Prometheus instrumentation.

The emission side of observability, distinct from the domain `MetricsPort`
(`free_memory_gb`), which is the ingestion side that feeds the memory budget a
live figure and still waits for the Mac Studio to produce a real one. This
module exposes what the process is *doing*; that port reads what the hardware
*has*.

Each application owns its own `CollectorRegistry`, held on `app.state` rather
than the library's default global registry, for the same reason every other
singleton lives there: a test builds an app with its own wiring and must not
inherit counters a previous test left in a process-wide registry. It also keeps
the three ASGI apps in one process from colliding on metric names.

Instrument choices worth the note:

- Inference metrics are derived from the `UsageRecord` the streaming path
  already produces, through `MeteredUsageRepository`, so the delicate generator
  in `RouteChatRequest` is not touched to be observed.
- The concurrency gauge is a scrape-time reading of the live limiter rather than
  a counter the request path increments, so it cannot drift out of step with the
  semaphore it is meant to report.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord
from app.domain.ports.infrastructure_ports import ConcurrencyLimiterPort
from app.domain.ports.repositories import UsageRepositoryPort

logger = logging.getLogger(__name__)

# One bucket set for both HTTP and inference latency. A gateway request is a
# streaming completion whose duration is the whole stream, so the default
# buckets (topping out at 10s) would collapse every real generation into +Inf.
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)


class Metrics:
    """The instruments for one application, all bound to `registry`."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry

        self.http_requests = Counter(
            "nexus_http_requests_total",
            "HTTP requests by method, matched route template, and status.",
            ["method", "path", "status"],
            registry=registry,
        )
        self.http_duration = Histogram(
            "nexus_http_request_duration_seconds",
            "HTTP request duration, from first byte in to last byte out.",
            ["method", "path"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )
        self.http_in_progress = Gauge(
            "nexus_http_requests_in_progress",
            "HTTP requests currently being served.",
            registry=registry,
        )

        # Labelled by capability and model rather than by caller: a per-key or
        # per-tenant label would be unbounded cardinality, and the same figures
        # are already in usage_records for that breakdown.
        self.inference_requests = Counter(
            "nexus_inference_requests_total",
            "Completions served, by capability, model, and whether they ran to completion.",
            ["capability", "model", "completed"],
            registry=registry,
        )
        self.inference_tokens = Counter(
            "nexus_inference_tokens_total",
            "Tokens produced, counted even when a client disconnects mid-stream.",
            ["capability", "model"],
            registry=registry,
        )
        self.inference_duration = Histogram(
            "nexus_inference_duration_seconds",
            "Wall-clock time a completion held a concurrency slot.",
            ["capability", "model"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )

    def observe_http(self, method: str, path: str, status: int, elapsed_seconds: float) -> None:
        self.http_requests.labels(method, path, str(status)).inc()
        self.http_duration.labels(method, path).observe(elapsed_seconds)

    def observe_inference(self, record: UsageRecord) -> None:
        completed = "true" if record.completed else "false"
        self.inference_requests.labels(record.capability, record.model_alias, completed).inc()
        # A disconnect before the first token produces a zero-token record; the
        # request counter still moves, so a rejection rate is visible.
        self.inference_tokens.labels(record.capability, record.model_alias).inc(record.tokens)
        self.inference_duration.labels(record.capability, record.model_alias).observe(
            record.latency_ms / 1000
        )


class _ConcurrencyCollector(Collector):
    """Reports the inference limiter's saturation at scrape time.

    Read live rather than tracked through the request path: slot saturation is
    the single pressure the resource guardrails exist to bound, and a gauge that
    could disagree with the semaphore would be worse than none.
    """

    def __init__(self, limiter: ConcurrencyLimiterPort) -> None:
        self._limiter = limiter

    def collect(self) -> Iterable[GaugeMetricFamily]:
        limit = self._limiter.limit
        in_use = limit - self._limiter.available
        used = GaugeMetricFamily(
            "nexus_inference_slots_in_use",
            "Inference concurrency slots currently held.",
        )
        used.add_metric([], in_use)
        cap = GaugeMetricFamily(
            "nexus_inference_slots_max",
            "Total inference concurrency slots configured.",
        )
        cap.add_metric([], limit)
        yield used
        yield cap


def build_metrics(limiter: ConcurrencyLimiterPort | None = None) -> Metrics:
    """A fresh registry and instruments for one application.

    The concurrency collector is registered only where a limiter exists, which
    is every entrance that can run inference (the gateway and both admin apps
    via `/admin/chat`).
    """
    registry = CollectorRegistry()
    metrics = Metrics(registry)
    if limiter is not None:
        registry.register(_ConcurrencyCollector(limiter))
    return metrics


def render(metrics: Metrics) -> tuple[bytes, str]:
    """The exposition body and its content type."""
    return generate_latest(metrics.registry), CONTENT_TYPE_LATEST


class MeteredUsageRepository:
    """Wraps a usage repository to emit inference metrics as records are written.

    Instrumenting here rather than in `RouteChatRequest` keeps the streaming
    contract's generator untouched: the use case already builds one `UsageRecord`
    carrying tokens, latency and completion, in a `finally` that runs on normal
    completion, disconnect and error alike, which is exactly the set of events
    worth counting.

    The persistence write goes first, and the metric emission is guarded, so the
    two failure modes cannot cross: a metrics error must never lose the usage row
    (billing is the more important of the two), and a persistence error, which
    the use case already swallows, simply means no metric for that request.
    """

    def __init__(self, inner: UsageRepositoryPort, metrics: Metrics) -> None:
        self._inner = inner
        self._metrics = metrics

    async def record(self, usage: UsageRecord) -> None:
        await self._inner.record(usage)
        try:
            self._metrics.observe_inference(usage)
        except Exception:  # noqa: BLE001
            logger.warning("failed to emit inference metrics", exc_info=True)

    async def tokens_used_today(self, api_key_id: str) -> int:
        return await self._inner.tokens_used_today(api_key_id)

    async def last_used_by_key(self) -> dict[str, datetime]:
        return await self._inner.last_used_by_key()

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        return await self._inner.totals_since(since)

    async def bucketed_usage(
        self,
        since: datetime,
        until: datetime,
        unit: BucketUnit,
        *,
        actor_id: str | None = None,
    ) -> list[UsageBucket]:
        return await self._inner.bucketed_usage(since, until, unit, actor_id=actor_id)
