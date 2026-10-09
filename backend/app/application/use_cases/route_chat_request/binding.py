"""Binding a chat request to the one attempt that may run for it.

Final spec §5 and design R6/S6 on #24, with the maintainer's decisions Q2-Q4.
Used only while node agents are enabled: an attempt is something an agent
records, and with direct runtimes there is nothing to look a repeat up in.

- **Every request is bound** before it is forwarded. A request with an
  `Idempotency-Key` is bound under that key; one without is bound under a
  fresh id no client can repeat, so its billing still has a home (step (c)).
- **A repeat of a key** is answered from the bound attempt, on the node it was
  bound to, and never run again: a stored result is replayed as one chunk, an
  unfinished or unknown attempt is a 409, and so is a failure or an expired
  result. Only an attempt that provably never ran (`cancelled_unsent`) may be
  replaced by a new one.
- **The hash** identifies what the client sent, before any server-side step,
  and is compared using the version the binding was made with.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from app.domain.entities.actor import Actor
from app.domain.entities.attempt import AttemptIdentity, Binding, RequestIdentity
from app.domain.entities.chat import CompletionChunk
from app.domain.entities.model import RuntimeKind
from app.domain.exceptions import (
    IdempotencyAttemptFailedError,
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyResultExpiredError,
    NoAvailableModelError,
)
from app.domain.ports.model_runtime_port import ModelRuntimePort, runtime_for
from app.domain.ports.repositories import NodeRepositoryPort
from app.domain.ports.request_binding_port import (
    AttemptLedgerPort,
    AttemptView,
    RequestBindingPort,
)

HASH_VERSION = "v1"

_UNFINISHED = frozenset({"accepted", "running", "outcome_unknown"})


def _canonical_v1(identity: RequestIdentity) -> bytes:
    return json.dumps(
        {"shape": identity.shape, "body": identity.body},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


CANONICALISERS: dict[str, Callable[[RequestIdentity], bytes]] = {"v1": _canonical_v1}
"""Every canonical form ever stored. A form is never changed or removed once a
binding may carry its version; a new form is a new version (review on #24)."""


def payload_hash(identity: RequestIdentity, version: str = HASH_VERSION) -> str:
    canonical = CANONICALISERS.get(version)
    if canonical is None:
        raise NoAvailableModelError(detail=f"no canonicaliser for hash version {version!r}")
    return f"{version}:{hashlib.sha256(canonical(identity)).hexdigest()}"


def keyed_request_id(key: str) -> str:
    """Client keys and minted ids share one column, so they never collide."""
    return f"k:{key}"


_INTERNAL = RequestIdentity(key=None, shape="internal", body={})
"""For a caller that is not an HTTP request (the management assistant): its
request can never be repeated, so what it hashes to does not matter."""


class RequestBinder:
    def __init__(
        self,
        bindings: RequestBindingPort,
        nodes: NodeRepositoryPort,
        runtimes: Mapping[RuntimeKind, ModelRuntimePort],
        request_id: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._bindings = bindings
        self._nodes = nodes
        self._runtimes = runtimes
        self._request_id = request_id

    async def repeat(
        self, actor: Actor, identity: RequestIdentity | None
    ) -> list[CompletionChunk] | None:
        """The answer to a repeated key, or None when the request may proceed.

        Runs after authentication and before any server-side step: templates,
        retrieval, compaction (design R6).
        """
        if identity is None or identity.key is None:
            return None
        binding = await self._bindings.lookup(actor.tenant_id, keyed_request_id(identity.key))
        if binding is None:
            return None
        self._check_hash(binding, identity)
        return await self._existing(binding, may_cancel=True)

    async def bind(
        self,
        actor: Actor,
        identity: RequestIdentity | None,
        node_id: str,
        billing: dict[str, Any],
    ) -> AttemptIdentity | list[CompletionChunk]:
        """The attempt to run on `node_id`, or the answer of the one that won."""
        identity = identity or _INTERNAL
        keyed = identity.key is not None
        request_id = (
            keyed_request_id(identity.key)
            if identity.key is not None
            else f"r:{self._request_id() or uuid.uuid4()}"
        )
        hashed = payload_hash(identity)
        op_id = str(uuid.uuid4())
        bound = await self._bindings.create(
            tenant_id=actor.tenant_id,
            request_id=request_id,
            payload_hash=hashed,
            hash_version=HASH_VERSION,
            key_supplied=keyed,
            billing=billing,
            node_id=node_id,
            op_id=op_id,
        )
        if bound.op_id != op_id:
            # Another copy of this keyed request bound first. Its attempt is
            # never cancelled from here: it may be on its way to the agent
            # right now, and a concurrent duplicate converges on it instead.
            # A binding left by a forward that was lost is cancelled by
            # `repeat`, which every keyed request passes first.
            self._check_hash(bound, identity)
            existing = await self._existing(bound, may_cancel=False)
            if existing is not None:
                return existing
            bound = await self._bindings.rebind(bound, node_id=node_id, op_id=op_id)
            if bound.op_id != op_id:
                # Lost the rebind as well; converge on the winner the same way.
                existing = await self._existing(bound, may_cancel=False)
                if existing is not None:
                    return existing
                raise IdempotencyInProgressError(detail=f"{request_id} was rebound concurrently")
        return AttemptIdentity(
            op_id=op_id, request_id=request_id, payload_hash=hashed, store_output=keyed
        )

    @staticmethod
    def _check_hash(binding: Binding, identity: RequestIdentity) -> None:
        if payload_hash(identity, binding.hash_version) != binding.payload_hash:
            raise IdempotencyKeyReusedError(
                detail=f"{binding.request_id} is bound to a different payload"
            )

    async def _existing(
        self, binding: Binding, *, may_cancel: bool
    ) -> list[CompletionChunk] | None:
        """Answer from the bound attempt; None only when it provably never ran."""
        ledger = await self._ledger(binding.node_id)
        view = await ledger.describe(binding.op_id)
        if view is None:
            if not may_cancel:
                raise IdempotencyInProgressError(detail=f"{binding.op_id} is bound, not yet sent")
            # Bound, but the agent never saw it: the forward was lost or has
            # not arrived. A tombstone makes any late arrival only observe it,
            # and only then may the request move (design R6).
            view = await ledger.cancel(binding.op_id, "inference")
        if view.state == "cancelled_unsent":
            return None
        if view.state == "completed":
            if view.result is None:
                raise IdempotencyResultExpiredError(detail=f"{binding.op_id} has no stored result")
            return ledger.replay(str(binding.billing.get("model_ref", "")), view)
        if view.state == "failed":
            raise IdempotencyAttemptFailedError(detail=f"{binding.op_id} failed: {view.reason}")
        if view.state in _UNFINISHED:
            raise IdempotencyInProgressError(detail=f"{binding.op_id} is {view.state}")
        raise IdempotencyInProgressError(detail=f"{binding.op_id} is in state {view.state!r}")

    async def _ledger(self, node_id: str) -> AttemptLedgerPort:
        node = await self._nodes.get(node_id)
        runtime = runtime_for(self._runtimes, node, RuntimeKind.OLLAMA)
        if not isinstance(runtime, AttemptLedgerPort):
            # Never answered by running again: without the bound node's agent
            # there is no evidence of what the attempt did.
            raise NoAvailableModelError(detail=f"no node agent reachable for node {node_id}")
        return runtime


def billing_snapshot(
    actor: Actor,
    *,
    capability: str,
    requested_capability: str | None,
    model_alias: str,
    model_ref: str,
    node_id: str,
    started_at: str,
    compaction: dict[str, int | None],
) -> dict[str, Any]:
    """Everything a usage row needs that the agent does not know (design S6),
    fixed once, when the request is bound."""
    return {
        "actor_id": actor.id,
        "api_key_id": actor.api_key_id,
        "tenant_id": actor.tenant_id,
        "capability": capability,
        "requested_capability": requested_capability,
        "model_alias": model_alias,
        "model_ref": model_ref,
        "node_id": node_id,
        "started_at": started_at,
        "compaction": compaction,
    }


__all__ = [
    "CANONICALISERS",
    "HASH_VERSION",
    "AttemptView",
    "RequestBinder",
    "billing_snapshot",
    "keyed_request_id",
    "payload_hash",
]
