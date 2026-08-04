"""The compute host's free memory and disk, for the Nodes screen.

Behind `node:read`, the same scope as the node it describes: this is a property
of the machine the runtimes run on, not a separate resource. Operators and
auditors hold it; a member does not, which is deliberate — a `user` was
deliberately denied the node read because it exposes the tailnet address, and
the free memory of the server is the same class of fact.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.host import HostStatus
from app.domain.ports.host_status_port import HostStatusPort
from app.domain.ports.security_ports import AuthorizationPort


class ReadHostStatus:
    def __init__(self, host: HostStatusPort, authz: AuthorizationPort) -> None:
        self._host = host
        self._authz = authz

    async def execute(self, actor: Actor) -> HostStatus | None:
        """`None` when the agent is not reachable, which the screen renders as
        "not reporting" rather than as an error: not having installed an
        optional launchd job is a state, not a fault."""
        self._authz.require(actor, Scope.NODE_READ)
        return await self._host.read()
