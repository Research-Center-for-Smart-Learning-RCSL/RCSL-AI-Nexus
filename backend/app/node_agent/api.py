"""The node agent's HTTP surface.

Every route but `/healthz` needs the shared agent token, compared in constant
time; the agent will be reached over the tailnet once a second node exists, so
network isolation alone is not the boundary (design revision 1 §2 on #24).

`/v1/inference` streams NDJSON: `accepted`, then the runtime's lines as the
agent reads them, then one `terminal` event. The terminal event is sent only
after the attempt's terminal state is committed, so a caller that saw it can
rely on `GET /v1/attempts/{op_id}` saying the same (design R6). A caller that
goes away stops delivery and nothing else.
"""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.adapters.runtime.ollama_adapter.encoding import chat_payload, embed_payload
from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.node_agent.dispatch import Attempt, Completed, Existing, Outcome, Refused
from app.node_agent.guard import GuardRefusal, check_generation, check_pin, registration
from app.node_agent.resolution import ResolutionRefused
from app.node_agent.service import Agent, start, stop
from app.node_agent.settings import AgentSettings
from app.node_agent.store import LIFECYCLE_KINDS, NotOwner, Operation
from app.node_agent.wire import (
    Envelope,
    LifecycleRequest,
    WireError,
    decode_embedding,
    decode_generation,
    decode_lifecycle,
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024 * 1024
RUNTIME = "ollama"
CANCELLABLE_KINDS = ("inference", "embedding_batch")


def _agent(request: Request) -> Agent:
    agent: Agent = request.app.state.agent
    return agent


async def _authorised(request: Request) -> None:
    expected = _agent(request).settings.token
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="agent token required")


async def _body(request: Request) -> Any:
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise HTTPException(status_code=400, detail="bad Content-Length")
        if int(declared) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body too large")
    # Read with the bound applied as it arrives, so a chunked body without a
    # length is cut off at the cap rather than buffered whole first.
    parts: list[bytes] = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body too large")
        parts.append(part)
    raw = b"".join(parts)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="body is not JSON") from exc


async def _describe(agent: Agent, operation: Operation) -> dict[str, Any]:
    described: dict[str, Any] = {
        "op_id": operation.op_id,
        "kind": operation.kind,
        "state": operation.state,
        "reason": operation.reason,
        "terminal": operation.terminal,
        "replay_unavailable": operation.replay_unavailable,
    }
    if operation.state == "completed" and operation.store_output:
        described["result"] = await agent.store.stored_result(operation.op_id)
    return described


async def _existing(
    agent: Agent, operation: Operation, kind: str, envelope: Envelope
) -> JSONResponse:
    """An op id that already exists, answered only to the request it belongs to.

    A different kind or payload hash under the same op id is a conflict, never
    the other request's state or result (review of #33's branch). A tombstone
    carries no hash, so a late original still observes it.
    """
    if operation.kind != kind or (
        operation.payload_hash is not None and operation.payload_hash != envelope.payload_hash
    ):
        return JSONResponse(
            status_code=409, content={"op_id": operation.op_id, "refused": "op_id_conflict"}
        )
    return JSONResponse(await _describe(agent, operation))


def _refused(refusal: Refused) -> JSONResponse:
    headers = {} if refusal.retry_after is None else {"Retry-After": str(refusal.retry_after)}
    content: dict[str, Any] = {"refused": refusal.reason}
    if refusal.operation is not None:
        content["state"] = refusal.operation.state
    return JSONResponse(status_code=503, content=content, headers=headers)


def _guard_refused(refusal: GuardRefusal) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"refused": refusal.reason, "detail": refusal.detail}
    )


async def _measure(agent: Agent, ref: str, request: Any = None) -> Measurement:
    if agent.counter is None:
        return Measurement(identity=None, counted=None, declared_context=None)
    messages = request.messages if request is not None else ()
    tools = request.tools if request is not None else ()
    return await agent.counter.measure(ref, messages, tools)


def create_app(settings: AgentSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        agent = await start(settings or AgentSettings())  # type: ignore[call-arg]
        app.state.agent = agent
        try:
            yield
        finally:
            await stop(agent)

    app = FastAPI(
        title="RCSL AI Nexus node agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    authorised = [Depends(_authorised)]

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, str]:
        return {"status": "ok", "gate": _agent(request).dispatcher.state.value}

    @app.get("/v1/status", dependencies=authorised)
    async def status(request: Request) -> dict[str, Any]:
        agent = _agent(request)
        return {
            "node_id": agent.settings.node_id,
            "generation": agent.elected.ownership.generation,
            "boot_id": agent.elected.ownership.boot_id,
            "domain_id": agent.host_lock.domain.domain_id,
            "host_lock_held": agent.host_lock.still_held(),
            "gate": agent.dispatcher.state.value,
            "admitted": agent.dispatcher.admitted,
            "unknown": await agent.store.any_unknown(),
            "runtime_version": (version := await agent.relay.version()),
            "runtime_reachable": version is not None,
        }

    @app.post("/v1/inference", dependencies=authorised, response_model=None)
    async def inference(request: Request) -> StreamingResponse | JSONResponse:
        agent = _agent(request)
        try:
            generation, envelope = decode_generation(await _body(request))
        except WireError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = await agent.store.observe(envelope.op_id)
        if existing is not None:
            return await _existing(agent, existing, "inference", envelope)

        registered = await registration(agent.pool, agent.settings.node_id, RUNTIME, generation.ref)
        measured = await _measure(agent, generation.ref, generation)
        verdict = check_generation(generation, registered, measured, node_id=agent.settings.node_id)
        if isinstance(verdict, GuardRefusal) and verdict.reason == "context_exceeded":
            # Only where the legacy rule refuses: the runtime's version, read
            # now, is the last part of a validated profile's key (PR2b).
            verdict = check_generation(
                generation,
                registered,
                measured,
                node_id=agent.settings.node_id,
                runtime_version=await agent.relay.version(),
            )
        if isinstance(verdict, GuardRefusal):
            return _guard_refused(verdict)
        payload = chat_payload(
            generation.ref,
            generation.messages,
            max_tokens=generation.max_tokens,
            thinking=generation.thinking,
            tools=generation.tools,
            tool_choice=generation.tool_choice,
            sampling=generation.sampling,
            context_length=generation.context_length,
            keep_alive=agent.keep_alive,
        )
        submitted = await agent.dispatcher.submit(
            envelope.op_id,
            "inference",
            agent.relay.chat(
                payload, store_output=envelope.store_output, expected_identity=verdict.identity
            ),
            request_id=envelope.request_id,
            payload_hash=envelope.payload_hash,
            store_output=envelope.store_output,
            provenance=verdict.provenance,
            deadline_s=agent.settings.queue_deadline_s,
        )
        if isinstance(submitted, Existing):
            return await _existing(agent, submitted.operation, "inference", envelope)
        if isinstance(submitted, Refused):
            return _refused(submitted)
        return StreamingResponse(_stream(agent, submitted), media_type="application/x-ndjson")

    @app.post("/v1/embeddings", dependencies=authorised)
    async def embeddings(request: Request) -> JSONResponse:
        agent = _agent(request)
        try:
            batch, envelope = decode_embedding(await _body(request))
        except WireError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = await agent.store.observe(envelope.op_id)
        if existing is not None:
            return await _existing(agent, existing, "embedding_batch", envelope)
        registered = await registration(agent.pool, agent.settings.node_id, RUNTIME, batch.ref)
        if registered is None:
            return _guard_refused(
                GuardRefusal("model_not_on_node", f"{batch.ref} is not registered on this node")
            )
        measured = await _measure(agent, batch.ref)
        pinned = check_pin(registered, measured.identity)
        if pinned is not None:
            return _guard_refused(pinned)
        submitted = await agent.dispatcher.submit(
            envelope.op_id,
            "embedding_batch",
            agent.relay.embed(
                embed_payload(batch.ref, batch.texts, keep_alive=agent.keep_alive),
                store_output=envelope.store_output,
                expected_identity=measured.identity,
            ),
            request_id=envelope.request_id,
            payload_hash=envelope.payload_hash,
            store_output=envelope.store_output,
            provenance={"manifest": measured.identity, "texts": len(batch.texts)},
            deadline_s=agent.settings.queue_deadline_s,
        )
        if isinstance(submitted, Existing):
            return await _existing(agent, submitted.operation, "embedding_batch", envelope)
        if isinstance(submitted, Refused):
            return _refused(submitted)
        vectors: Any = None
        async for event in submitted.events():
            if event.get("type") == "embeddings":
                vectors = event.get("data")
        await submitted.settled
        operation = await agent.store.observe(envelope.op_id)
        if operation is None:
            raise HTTPException(status_code=500, detail="attempt vanished")
        described = await _describe(agent, operation)
        if operation.state == "completed":
            described["embeddings"] = vectors
            return JSONResponse(described)
        return JSONResponse(
            status_code=502 if operation.state == "failed" else 503, content=described
        )

    @app.post("/v1/lifecycle/{action}", dependencies=authorised, response_model=None)
    async def lifecycle(request: Request, action: str) -> StreamingResponse | JSONResponse:
        """`load`, `unload` or `pull`, with the node to itself (PR4b).

        A pull streams `accepted`, its progress and one `terminal` event, as
        an inference does; a load or unload answers once it has settled.
        """
        if action not in LIFECYCLE_KINDS:
            raise HTTPException(status_code=404, detail=f"no lifecycle action {action}")
        agent = _agent(request)
        try:
            wanted = decode_lifecycle(await _body(request))
        except WireError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = await agent.store.observe(wanted.op_id)
        if existing is not None:
            return await _existing_lifecycle(agent, existing, action)

        registered = await registration(agent.pool, agent.settings.node_id, RUNTIME, wanted.ref)
        if registered is None:
            return _guard_refused(
                GuardRefusal("model_not_on_node", f"{wanted.ref} is not registered on this node")
            )
        context_length = None
        if action == "load":
            # The registration decides the runner's size, as it does for every
            # request the agent sends; a caller may not size it otherwise.
            context_length = registered.context_length or wanted.context_length
            if (
                wanted.context_length is not None
                and registered.context_length > 0
                and wanted.context_length != registered.context_length
            ):
                return _guard_refused(
                    GuardRefusal(
                        "context_length_mismatch",
                        f"requested {wanted.context_length}, "
                        f"registered {registered.context_length}",
                    )
                )
        if action == "load":
            relay = agent.relay.load(
                wanted.ref, keep_alive=agent.keep_alive, context_length=context_length
            )
        elif action == "unload":
            relay = agent.relay.unload(wanted.ref)
        else:
            relay = agent.relay.pull(wanted.ref)
        submitted = await agent.dispatcher.exclusive(
            wanted.op_id,
            action,
            relay,
            provenance={"ref": wanted.ref, "context_length": context_length},
            after=_repin(agent, wanted) if action == "pull" else None,
        )
        if isinstance(submitted, Existing):
            return await _existing_lifecycle(agent, submitted.operation, action)
        if isinstance(submitted, Refused):
            return _refused(submitted)
        if action == "pull":
            return StreamingResponse(_stream(agent, submitted), media_type="application/x-ndjson")
        async for _ in submitted.events():
            pass
        await submitted.settled
        operation = await agent.store.observe(wanted.op_id)
        if operation is None:
            raise HTTPException(status_code=500, detail="operation vanished")
        return await _existing_lifecycle(agent, operation, action)

    @app.get("/v1/residency", dependencies=authorised)
    async def residency(request: Request) -> JSONResponse:
        """What the runtime holds and has on disk, read-only. Observing changes
        nothing, so it is answered whatever the gate says."""
        observed = await _agent(request).relay.residency()
        if observed is None:
            return JSONResponse(status_code=503, content={"refused": "runtime_unobserved"})
        return JSONResponse(observed)

    @app.get("/v1/attempts/{op_id}", dependencies=authorised)
    async def attempt(request: Request, op_id: str) -> JSONResponse:
        agent = _agent(request)
        operation = await agent.store.observe(op_id)
        if operation is None:
            return JSONResponse(status_code=404, content={"op_id": op_id, "state": "absent"})
        return JSONResponse(await _describe(agent, operation))

    @app.post("/v1/attempts/{op_id}/cancel", dependencies=authorised)
    async def cancel(request: Request, op_id: str, kind: str) -> JSONResponse:
        # The kind is the caller's: a cancel that arrives before the original
        # leaves a tombstone, and the tombstone must say what it stands for.
        if kind not in CANCELLABLE_KINDS:
            raise HTTPException(status_code=400, detail=f"kind must be one of {CANCELLABLE_KINDS}")
        agent = _agent(request)
        try:
            operation = await agent.store.cancel_accepted(op_id, "cancel_requested", kind=kind)
        except NotOwner:
            await agent.dispatcher.lose_role("not_owner_at_cancel")
            return JSONResponse(status_code=503, content={"refused": "node_lost"})
        if operation is None:
            raise HTTPException(status_code=500, detail="cancellation left no row")
        return JSONResponse(await _describe(agent, operation))

    @app.post("/v1/drain", dependencies=authorised)
    async def drain(request: Request) -> dict[str, Any]:
        agent = _agent(request)
        await agent.dispatcher.drain()
        return {"gate": agent.dispatcher.state.value, "admitted": agent.dispatcher.admitted}

    @app.post("/v1/resume", dependencies=authorised)
    async def resume(request: Request) -> dict[str, Any]:
        state = await _agent(request).dispatcher.reopen()
        return {"gate": state.value}

    @app.post("/v1/maintenance/resolutions", dependencies=authorised)
    async def start_resolution(request: Request) -> JSONResponse:
        body = await _body(request)
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        try:
            started = await _agent(request).resolutions.start(
                str(body.get("op_id", "")),
                evidence=str(body.get("evidence", "")),
                operator=str(body.get("operator", "")),
            )
        except ResolutionRefused as exc:
            return JSONResponse(status_code=409, content={"refused": str(exc)})
        return JSONResponse(started)

    @app.post("/v1/maintenance/resolutions/{resolution_id}/complete", dependencies=authorised)
    async def complete_resolution(request: Request, resolution_id: str) -> JSONResponse:
        try:
            done = await _agent(request).resolutions.complete(resolution_id)
        except ResolutionRefused as exc:
            return JSONResponse(status_code=409, content={"refused": str(exc)})
        return JSONResponse(done)

    return app


async def _existing_lifecycle(agent: Agent, operation: Operation, action: str) -> JSONResponse:
    if operation.kind != action:
        return JSONResponse(
            status_code=409, content={"op_id": operation.op_id, "refused": "op_id_conflict"}
        )
    described = await _describe(agent, operation)
    status = {"completed": 200, "failed": 502}.get(operation.state, 202)
    return JSONResponse(status_code=status, content=described)


def _repin(agent: Agent, wanted: LifecycleRequest) -> Callable[[Outcome], Awaitable[None]]:
    """After a completed pull and before the node serves again, pin what the
    runtime now serves for the tag (design S5). If the runtime cannot say,
    the old pin stays, and dispatch against the new weights is refused as a
    revision mismatch until an operator re-pins: closed, not open."""

    async def after(outcome: Outcome) -> None:
        if not isinstance(outcome, Completed):
            return
        digest = await agent.relay.served_digest(wanted.ref)
        if digest is None:
            logger.error("pulled %s but the runtime does not list it; pin unchanged", wanted.ref)
            return
        moved = await agent.store.repin(wanted.op_id, RUNTIME, wanted.ref, digest)
        await agent.store.audit(
            "repin", wanted.op_id, {"ref": wanted.ref, "digest": digest, "models": moved}
        )

    return after


async def _stream(agent: Agent, attempt: Attempt) -> AsyncIterator[bytes]:
    try:
        yield _line({"type": "accepted", "op_id": attempt.op_id})
        async for event in attempt.events():
            yield _line(event)
        await attempt.settled
        operation = await agent.store.observe(attempt.op_id)
        yield _line(
            {
                "type": "terminal",
                "op_id": attempt.op_id,
                "state": operation.state if operation else "absent",
                "reason": operation.reason if operation else None,
                "terminal": operation.terminal if operation else None,
                "replay_unavailable": operation.replay_unavailable if operation else False,
                # The runtime's outcome says nothing about what this caller
                # received; events dropped for a slow reader are said so here.
                "delivery_complete": not attempt.delivery_lost,
            }
        )
    finally:
        attempt.abandon()


def _line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()
