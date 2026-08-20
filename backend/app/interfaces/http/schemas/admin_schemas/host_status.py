"""Admin host status schemas."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.entities.host import HostStatus


class HostMemoryResponse(BaseModel):
    total_gb: float | None
    available_gb: float | None
    swap_used_gb: float | None


class HostDiskResponse(BaseModel):
    volume: str | None
    total_gb: float | None
    free_gb: float | None


class HostSystemResponse(BaseModel):
    load_1m: float | None
    load_5m: float | None
    load_15m: float | None
    cpu_count: int | None
    uptime_seconds: int | None


class HostStatusResponse(BaseModel):
    reporting: bool
    """False when the agent could not be reached. The fields below are then all
    null, and the screen says so rather than drawing zeros — "no answer" and
    "none left" are opposite states and must not render alike."""

    memory: HostMemoryResponse
    disk: HostDiskResponse
    system: HostSystemResponse

    @classmethod
    def of(cls, status: HostStatus | None) -> HostStatusResponse:
        if status is None:
            return cls(
                reporting=False,
                memory=HostMemoryResponse(total_gb=None, available_gb=None, swap_used_gb=None),
                disk=HostDiskResponse(volume=None, total_gb=None, free_gb=None),
                system=HostSystemResponse(
                    load_1m=None, load_5m=None, load_15m=None, cpu_count=None, uptime_seconds=None
                ),
            )
        return cls(
            reporting=True,
            memory=HostMemoryResponse(
                total_gb=status.memory.total_gb,
                available_gb=status.memory.available_gb,
                swap_used_gb=status.memory.swap_used_gb,
            ),
            disk=HostDiskResponse(
                volume=status.disk.volume,
                total_gb=status.disk.total_gb,
                free_gb=status.disk.free_gb,
            ),
            system=HostSystemResponse(
                load_1m=status.system.load_1m,
                load_5m=status.system.load_5m,
                load_15m=status.system.load_15m,
                cpu_count=status.system.cpu_count,
                uptime_seconds=status.system.uptime_seconds,
            ),
        )
