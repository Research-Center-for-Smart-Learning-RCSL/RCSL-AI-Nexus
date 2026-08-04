"""Reading the host's own free memory and disk.

A port rather than a direct call because the thing it talks to is optional
infrastructure: the agent is a launchd job that a deployment may not have
installed, and the use case's job is to say "not available" rather than to fail.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.host import HostStatus


class HostStatusPort(Protocol):
    async def read(self) -> HostStatus | None:
        """The current snapshot, or `None` when the agent cannot be reached.

        `None` rather than an exception: an absent agent is an ordinary state on
        a deployment that has not installed it, and a screen that shows "not
        reporting" is more useful than one that shows an error nobody can act on
        from the browser.
        """
        ...
