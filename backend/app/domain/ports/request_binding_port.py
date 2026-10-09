"""Where a request's attempts are bound, and how a bound attempt is looked up.

Final spec §5 and design R6/S6 on #24. A binding ties `(tenant, request id)`
to the one attempt that may run for it, `(node, op id)`, and is committed
before anything is forwarded, so two copies of one keyed request converge on
one attempt rather than each running its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.domain.entities.attempt import Binding
from app.domain.entities.chat import CompletionChunk


class RequestBindingPort(Protocol):
    async def lookup(self, tenant_id: str, request_id: str) -> Binding | None: ...

    async def create(
        self,
        *,
        tenant_id: str,
        request_id: str,
        payload_hash: str,
        hash_version: str,
        key_supplied: bool,
        billing: dict[str, Any],
        node_id: str,
        op_id: str,
    ) -> Binding:
        """Bind the request to this attempt, or return the binding that won.

        The caller compares the returned `op_id` with its own to learn which.
        """
        ...

    async def rebind(self, binding: Binding, *, node_id: str, op_id: str) -> Binding:
        """Point the binding at a new attempt, only if it is still `binding`.

        Called only once the current attempt is provably unsent. A caller that
        loses the race gets the winner's binding back and converges on it; the
        old attempt stays in the history, with lineage.
        """
        ...


@dataclass(frozen=True, slots=True)
class AttemptView:
    """What a node agent says about one attempt."""

    op_id: str
    state: str
    reason: str | None
    result: dict[str, Any] | None


@runtime_checkable
class AttemptLedgerPort(Protocol):
    """The attempt operations only a node agent has (design §1 on #24)."""

    async def describe(self, op_id: str) -> AttemptView | None:
        """None when the agent has no such attempt."""
        ...

    async def cancel(self, op_id: str, kind: str) -> AttemptView:
        """Make an absent or queued attempt `cancelled_unsent`; anything else
        is returned unchanged."""
        ...

    def replay(self, ref: str, view: AttemptView) -> list[CompletionChunk]:
        """A completed attempt's stored result, as one chunk (decision Q3)."""
        ...
