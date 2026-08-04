"""What the machine the runtimes are on has left.

Reported by a small agent running natively under launchd rather than read from
inside a container, because on macOS a container reads a Linux VM's memory and
disk. Those numbers are plausible and wrong, which is the worst kind. Same
constraint as the one that keeps the runtimes off Docker (ARCHITECTURE.md 0.1).

Every field is optional. The agent may be absent (not installed yet, or being
restarted), and a value it could not read is null rather than zero — "no answer"
and "none left" are opposite states, and a chart that renders them the same
would be at its most confident exactly when it is least informed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostMemory:
    total_gb: float | None
    available_gb: float | None
    swap_used_gb: float | None
    """Reported beside `available_gb` rather than folded into it: a machine that
    is swapping is in a different state from one merely low, and on a host whose
    purpose is holding model weights it is the state to notice before a load
    rather than after one."""


@dataclass(frozen=True, slots=True)
class HostDisk:
    volume: str | None
    total_gb: float | None
    free_gb: float | None


@dataclass(frozen=True, slots=True)
class HostSystem:
    load_1m: float | None
    load_5m: float | None
    load_15m: float | None
    cpu_count: int | None
    uptime_seconds: int | None


@dataclass(frozen=True, slots=True)
class HostStatus:
    memory: HostMemory
    disk: HostDisk
    system: HostSystem
