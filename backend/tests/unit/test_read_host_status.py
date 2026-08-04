"""The host status read, and the two states it must keep apart.

The whole point of this feature is a number that is true. The container cannot
see the Mac's memory, so a missing agent has to read as "not reporting" rather
than as zero — those are opposite states, and a panel that renders them alike is
at its most confident exactly when it knows least.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.read_host_status import ReadHostStatus
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.host import HostDisk, HostMemory, HostStatus, HostSystem
from app.domain.exceptions import NotAuthorizedError

_AUTHZ = RoleAuthorization()


def _actor(*scopes: Scope) -> Actor:
    return Actor(
        id="a1",
        display="someone@example.test",
        role=Role.OPERATOR,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t1",
    )


class FakeHost:
    def __init__(self, status: HostStatus | None) -> None:
        self._status = status
        self.reads = 0

    async def read(self) -> HostStatus | None:
        self.reads += 1
        return self._status


def _status() -> HostStatus:
    return HostStatus(
        memory=HostMemory(total_gb=64.0, available_gb=29.4, swap_used_gb=0.0),
        disk=HostDisk(volume="/", total_gb=3721.9, free_gb=3593.6),
        system=HostSystem(
            load_1m=3.1, load_5m=3.0, load_15m=2.8, cpu_count=16, uptime_seconds=776918
        ),
    )


async def test_it_needs_the_node_read_scope() -> None:
    """The same scope as the node it describes. A `user` is deliberately denied
    the node read because it exposes the tailnet address, and the server's free
    memory is the same class of fact."""
    host = FakeHost(_status())
    use_case = ReadHostStatus(host, _AUTHZ)

    with pytest.raises(NotAuthorizedError):
        await use_case.execute(_actor(Scope.CHAT_USE))

    assert host.reads == 0, "authorisation is checked before the agent is called"


async def test_it_returns_what_the_agent_reported() -> None:
    use_case = ReadHostStatus(FakeHost(_status()), _AUTHZ)

    result = await use_case.execute(_actor(Scope.NODE_READ))

    assert result is not None
    assert result.memory.available_gb == 29.4
    assert result.disk.free_gb == 3593.6
    assert result.system.cpu_count == 16


async def test_an_unreachable_agent_is_none_rather_than_an_error() -> None:
    """Not having installed an optional launchd job is a state, not a fault.
    The screen says "not reporting"; it does not show an error nobody can act
    on from a browser, and it does not show zeros."""
    use_case = ReadHostStatus(FakeHost(None), _AUTHZ)

    assert await use_case.execute(_actor(Scope.NODE_READ)) is None
