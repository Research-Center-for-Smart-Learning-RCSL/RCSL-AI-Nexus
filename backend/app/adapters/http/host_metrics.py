"""Reads the launchd host-metrics agent over loopback.

The agent binds 127.0.0.1 and containers reach it through
`host.docker.internal`, exactly as they reach Ollama. No credential, matching
Ollama beside it: the boundary is the socket, and everything the agent reports
is readable by any process on that host with `vm_stat`.

A short timeout and a null on failure. This is drawn on a panel next to figures
that matter more; an admin screen that hangs because a status widget is waiting
on a socket has traded something valuable for something decorative.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.entities.host import HostDisk, HostMemory, HostStatus, HostSystem

logger = logging.getLogger(__name__)


def _f(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _i(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return int(value) if isinstance(value, (int, float)) else None


class HttpHostStatus:
    def __init__(self, base_url: str, timeout_seconds: float = 2.0) -> None:
        self._url = base_url
        self._timeout = timeout_seconds

    async def read(self) -> HostStatus | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            # Debug, not warning. On a deployment that never installed the agent
            # this is the steady state, and a warning per poll would be a log
            # full of a decision somebody already made.
            logger.debug("host_metrics_unavailable url=%s", self._url)
            return None

        memory = payload.get("memory") or {}
        disk = payload.get("disk") or {}
        system = payload.get("system") or {}
        volume = disk.get("volume")
        return HostStatus(
            memory=HostMemory(
                total_gb=_f(memory, "total_gb"),
                available_gb=_f(memory, "available_gb"),
                swap_used_gb=_f(memory, "swap_used_gb"),
            ),
            disk=HostDisk(
                volume=volume if isinstance(volume, str) else None,
                total_gb=_f(disk, "total_gb"),
                free_gb=_f(disk, "free_gb"),
            ),
            system=HostSystem(
                load_1m=_f(system, "load_1m"),
                load_5m=_f(system, "load_5m"),
                load_15m=_f(system, "load_15m"),
                cpu_count=_i(system, "cpu_count"),
                uptime_seconds=_i(system, "uptime_seconds"),
            ),
        )
