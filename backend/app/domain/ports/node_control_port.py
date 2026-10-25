"""The maintenance coordinator's calls to a node agent's control routes (P4 on #61)."""

from __future__ import annotations

from typing import Any, Protocol


class NodeControlError(Exception):
    """A node agent refused, failed or could not be reached.

    `status` is the HTTP status, None when nothing answered; `refused` is the
    agent's own refusal code when it gave one.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        refused: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.refused = refused
        self.body = body or {}


class NodeControlPort(Protocol):
    async def interrupt(self, epoch: int) -> dict[str, Any]:
        """Freeze the node for `epoch` and cancel every sender. The agent's
        report: `quiescent`, `interrupted`, `settling`, `still_sending`."""
        ...

    async def residency(self) -> list[dict[str, Any]] | None:
        """The runtime's `/api/ps` entries, read now, or None when it could
        not be asked. None is never an empty runtime."""
        ...

    async def reset(self, epoch: int, reset_id: str, *, operator: str) -> dict[str, Any]:
        """Restart the runtime empty under the hold, with witness evidence,
        and resolve the unknowns it covers. Repeating a `reset_id` returns
        the same reset."""
        ...
