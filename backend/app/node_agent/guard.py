"""The agent's own check of a request against its own node.

The gateway has already admitted the request, but against its view of the
registry and its own counter (final spec §1 on #24). The agent checks again,
before any durable row exists, against what it can see:

- the model is registered on this node, for this runtime and reference;
- the requested context equals the registration, since a different value
  would make the runtime start a second runner;
- when the model is pinned, the manifest the agent measured is the pinned one
  (design S5; `manifest_digest` is a weights pin, not residency intent);
- the prompt fits, by the PR2a contract: `P ≤ min(window // 2, window − 1 − O)`
  with the window the smaller of the registration and what the weights
  declare, and `P` counted from the same snapshot as that declaration.

A refusal here leaves nothing behind; a pass records what it was measured
against in the operation's provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.application.use_cases.route_chat_request.estimates import (
    _estimated_prompt_tokens,  # noqa: PLC2701 - the gateway's own fallback, on purpose
)
from app.node_agent.wire import GenerationRequest


@dataclass(frozen=True, slots=True)
class Registration:
    context_length: int
    manifest_digest: str | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuardRefusal:
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class GuardPass:
    provenance: dict[str, Any]
    identity: str | None


async def registration(
    pool: asyncpg.Pool, node_id: str, runtime: str, ref: str
) -> Registration | None:
    row = await pool.fetchrow(
        "SELECT context_length, manifest_digest, capabilities FROM models "
        "WHERE node_id = $1 AND runtime = $2 AND ref = $3",
        node_id,
        runtime,
        ref,
    )
    if row is None:
        return None
    capabilities = row["capabilities"]
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)
    return Registration(
        context_length=int(row["context_length"] or 0),
        manifest_digest=row["manifest_digest"],
        capabilities=tuple(str(c) for c in capabilities or ()),
    )


def check_pin(registered: Registration, identity: str | None) -> GuardRefusal | None:
    if registered.manifest_digest is not None and identity != registered.manifest_digest:
        return GuardRefusal(
            "revision_mismatch",
            f"the model store holds manifest {identity}, pinned is {registered.manifest_digest}",
        )
    return None


def check_generation(
    request: GenerationRequest,
    registered: Registration | None,
    measured: Measurement,
) -> GuardRefusal | GuardPass:
    if registered is None:
        return GuardRefusal("model_not_on_node", f"{request.ref} is not registered on this node")
    if registered.context_length > 0 and request.context_length != registered.context_length:
        return GuardRefusal(
            "context_length_mismatch",
            f"requested {request.context_length}, registered {registered.context_length}",
        )
    pinned = check_pin(registered, measured.identity)
    if pinned is not None:
        return pinned

    window = request.context_length
    if measured.declared_context is not None:
        window = min(window, measured.declared_context)
    servable = min(window // 2, window - 1 - request.max_tokens)
    if measured.counted is not None:
        counted, basis = measured.counted, "exact_counter"
    else:
        counted, _ = _estimated_prompt_tokens(request.messages, request.tools)
        basis = "estimate"
    provenance = {
        "manifest": measured.identity,
        "counted": counted,
        "basis": basis,
        "window": window,
        "servable": servable,
        "max_tokens": request.max_tokens,
    }
    if servable <= 0 or counted > servable:
        return GuardRefusal(
            "context_exceeded",
            f"prompt {counted} ({basis}) exceeds the {servable} servable in a {window}-token "
            f"window with {request.max_tokens} reserved for output",
        )
    return GuardPass(provenance=provenance, identity=measured.identity)
