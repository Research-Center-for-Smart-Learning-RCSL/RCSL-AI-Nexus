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
from typing import Any


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


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """What a client sent, and the key it named it by (final spec §5).

    `body` is the request as the client sent it: fields it omitted are absent,
    never filled with defaults (decision Q4), so a later change of default
    cannot make an identical retry look like key reuse. `shape` names the API
    the body belongs to, so the same JSON sent to two endpoints never hashes
    alike.
    """

    key: str | None
    shape: str
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Binding:
    """A request's current attempt (`request_bindings` and `request_attempts`)."""

    tenant_id: str
    request_id: str
    payload_hash: str
    hash_version: str
    key_supplied: bool
    version: int
    seq: int
    node_id: str
    op_id: str
    billing: dict[str, Any]
