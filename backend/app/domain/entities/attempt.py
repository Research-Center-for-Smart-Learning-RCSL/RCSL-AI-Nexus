"""The identity a runtime call carries to a node agent (final spec §5 on #24).

Set by the use case that bound the request, read by the agent adapter. A
context variable rather than a parameter of `ModelRuntimePort.generate`: the
port has eight implementations and fakes, and only the agent adapter has any
use for an identity; every other runtime ignores it by never reading it.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    op_id: str
    """The attempt's identity, unique platform-wide; `usage_records.attempt_id`
    holds the same value."""
    request_id: str | None
    payload_hash: str | None
    store_output: bool
    """True only for a request that carried an `Idempotency-Key` (decision Q2)."""

    @classmethod
    def unbound(cls) -> AttemptIdentity:
        """An attempt no client can repeat: no key, nothing stored."""
        return cls(op_id=str(uuid.uuid4()), request_id=None, payload_hash=None, store_output=False)


current_attempt: ContextVar[AttemptIdentity | None] = ContextVar("current_attempt", default=None)
