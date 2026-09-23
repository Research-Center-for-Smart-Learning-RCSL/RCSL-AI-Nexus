"""Implements MetricsPort by reading the launchd host-metrics agent."""

from __future__ import annotations

from app.adapters.http.host_metrics import fetch_host_metrics
from app.domain.ports.infrastructure_ports import MetricsPort


class HttpMetricsAdapter:
    """Reads live free memory from the host-metrics agent.

    Delegates the HTTP fetch to ``fetch_host_metrics``, shared with
    ``HttpHostStatus``, so a change to the agent's response format is
    applied once.

    **Single-node only.** ``node_id`` is accepted for the protocol but
    ignored: the agent runs on the local host and there is one. Per-node
    endpoints land with multi-node routing; until then, a second node's
    live memory is unavailable and the budget falls back to the static
    check, which is the pre-existing behaviour.
    """

    def __init__(self, base_url: str, timeout_seconds: float = 2.0) -> None:
        self._url = base_url
        self._timeout = timeout_seconds

    async def free_memory_gb(self, node_id: str) -> float | None:
        payload = await fetch_host_metrics(self._url, self._timeout)
        if payload is None:
            return None

        memory = payload.get("memory") or {}
        value = memory.get("available_gb")
        if isinstance(value, (int, float)):
            return float(value)
        return None


def _check_protocol() -> None:
    _adapter: MetricsPort = HttpMetricsAdapter("")  # noqa: F841
