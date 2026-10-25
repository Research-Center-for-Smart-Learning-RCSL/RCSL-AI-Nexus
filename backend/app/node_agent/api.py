"""The node agent's HTTP surface.

Every route but `/healthz` needs the shared agent token, compared in constant
time; the agent will be reached over the tailnet once a second node exists, so
network isolation alone is not the boundary (design revision 1 §2 on #24).

The routes that change what the node will do rather than ask it for work,
draining, resuming, resolving a block, interrupting senders and stopping or
restarting the runtime, need a second token instead (P3 on #61). The gateway
holds only the first, so nothing it can be made to send reaches them; the data
token is refused there, and the control token everywhere else but the
read-only `/v1/status`.

`/v1/inference` streams NDJSON: `accepted`, then the runtime's lines as the
agent reads them, then one `terminal` event. The terminal event is sent only
after the attempt's terminal state is committed, so a caller that saw it can
rely on `GET /v1/attempts/{op_id}` saying the same (design R6). A caller that
goes away stops delivery and nothing else.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.adapters.runtime.ollama_adapter.encoding import chat_payload, embed_payload
from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.application.use_cases.route_chat_request.compaction_tier2 import (
    SUMMARY_INPUT_MAX_BYTES,
    SUMMARY_OUTPUT_TOKENS,
    SUMMARY_TIMEOUT_SECONDS,
    SummaryTooLongError,
    build_summary_prompt,
)
from app.node_agent.dispatch import (
    Attempt,
    Completed,
    Existing,
    GateState,
    Outcome,
    Refused,
    Relay,
    RuntimeRefused,
    Sink,
)
from app.node_agent.guard import GuardRefusal, check_generation, check_pin, registration
from app.node_agent.relay import SUMMARY_IDLE_SECONDS
from app.node_agent.resolution import ResetFailed, ResolutionRefused
from app.node_agent.settings import AgentSettings
from app.node_agent.store import LIFECYCLE_KINDS, RESTORE_KINDS, NotOwner, Operation
from app.node_agent.summary import bounded_summary
from app.node_agent.supervisor import ACTIONS as SUPERVISOR_ACTIONS
from app.node_agent.supervisor import SupervisorRefused
from app.node_agent.wire import (
    Envelope,
    LifecycleRequest,
    WireError,
    decode_embedding,
    decode_generation,
    decode_lifecycle,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.node_agent.service import Agent

MAX_BODY_BYTES = 64 * 1024 * 1024
RUNTIME = "ollama"
CANCELLABLE_KINDS = ("inference", "embedding_batch", "summary")
RESET_ID = re.compile(r"[0-9a-f]{32}")


def _agent(request: Request) -> Agent:
    agent: Agent = request.app.state.agent
    return agent


def _bearer(request: Request) -> str | None:
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    return presented if scheme.lower() == "bearer" else None


async def _authorised(request: Request) -> None:
    expected = _agent(request).settings.token
    presented = _bearer(request)
    if presented is None or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="agent token required")


async def _controller(request: Request) -> None:
    expected = _agent(request).settings.control_token
    if expected is None:
        raise HTTPException(status_code=503, detail="no control token is configured")
    presented = _bearer(request)
    if presented is None or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="agent control token required")


async def _observer(request: Request) -> None:
    """Either token: `/v1/status` only reads, and the resolve CLI holds only
    the control token."""
    settings = _agent(request).settings
    presented = (_bearer(request) or "").encode()
    tokens = [settings.token] + ([settings.control_token] if settings.control_token else [])
    if not any(hmac.compare_digest(presented, token.encode()) for token in tokens):
        raise HTTPException(status_code=401, detail="agent token required")


def _text(body: Any, key: str, *, limit: int = 500) -> str:
    value = body.get(key) if isinstance(body, dict) else None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise HTTPException(status_code=400, detail=f"{key} must be text of at most {limit}")
    return value.strip()


async def _body(request: Request, *, max_bytes: int = MAX_BODY_BYTES) -> Any:
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise HTTPException(status_code=400, detail="bad Content-Length")
        if int(declared) > max_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
    # Read with the bound applied as it arrives, so a chunked body without a
    # length is cut off at the cap rather than buffered whole first.
    parts: list[bytes] = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > max_bytes:
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
    if request is None:
        return await agent.counter.measure_capacity(ref)
    messages = request.messages if request is not None else ()
    tools = request.tools if request is not None else ()
    return await agent.counter.measure(ref, messages, tools)


def create_app(settings: AgentSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.node_agent.service import start, stop

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
    controlled = [Depends(_controller)]

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, str]:
        return {"status": "ok", "gate": _agent(request).dispatcher.state.value}

    @app.get("/v1/status", dependencies=[Depends(_observer)])
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
            "quiescent": agent.dispatcher.quiescent,
            "maintenance_epoch": agent.dispatcher.frozen_epoch,
            "supervisor_available": agent.supervisor.available,
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

    @app.post("/v1/summary", dependencies=authorised)
    async def summary(request: Request) -> JSONResponse:
        agent = _agent(request)
        try:
            prefix, envelope = decode_generation(
                await _body(request, max_bytes=SUMMARY_INPUT_MAX_BYTES)
            )
        except WireError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = await agent.store.observe(envelope.op_id)
        if existing is not None:
            return await _existing(agent, existing, "summary", envelope)
        admission = await agent.dispatcher.summary_admission_refusal()
        if admission is not None:
            return _refused(admission)
        if agent.counter is None:
            return _guard_refused(
                GuardRefusal("summary_counter_unavailable", "exact counter required")
            )
        try:
            async with asyncio.timeout(SUMMARY_TIMEOUT_SECONDS):
                generation = replace(
                    prefix,
                    messages=tuple(build_summary_prompt(prefix.messages)),
                    max_tokens=SUMMARY_OUTPUT_TOKENS,
                    thinking=False,
                    tools=(),
                    tool_choice=None,
                    sampling=None,
                )
                registered = await registration(
                    agent.pool, agent.settings.node_id, RUNTIME, generation.ref
                )
                measured = await _measure(agent, generation.ref, generation)
                if measured.counted is None or measured.declared_context is None:
                    return _guard_refused(
                        GuardRefusal(
                            "summary_counter_unavailable", "exact count and capacity required"
                        )
                    )
                verdict = check_generation(
                    generation,
                    registered,
                    measured,
                    node_id=agent.settings.node_id,
                    runtime_version=await agent.relay.version(),
                )
        except (SummaryTooLongError, TimeoutError) as exc:
            return _guard_refused(GuardRefusal("summary_input_exceeded", str(exc)))
        if isinstance(verdict, GuardRefusal):
            return _guard_refused(verdict)
        payload = chat_payload(
            generation.ref,
            generation.messages,
            max_tokens=SUMMARY_OUTPUT_TOKENS,
            thinking=False,
            context_length=generation.context_length,
            keep_alive=agent.keep_alive,
            tools=(),
            tool_choice=None,
            sampling=None,
        )
        submitted = await agent.dispatcher.submit(
            envelope.op_id,
            "summary",
            bounded_summary(
                agent.relay.chat(
                    payload,
                    store_output=False,
                    expected_identity=verdict.identity,
                    idle_timeout_s=SUMMARY_IDLE_SECONDS,
                ),
                agent.counter,
                generation.ref,
            ),
            request_id=envelope.request_id,
            payload_hash=envelope.payload_hash,
            store_output=envelope.store_output,
            provenance=verdict.provenance,
            deadline_s=agent.settings.queue_deadline_s,
        )
        if isinstance(submitted, Existing):
            return await _existing(agent, submitted.operation, "summary", envelope)
        if isinstance(submitted, Refused):
            return _refused(submitted)
        text: str | None = None
        try:
            async with asyncio.timeout(SUMMARY_TIMEOUT_SECONDS):
                async for event in submitted.events():
                    if event.get("type") == "summary":
                        text = event["text"]
                await asyncio.shield(submitted.settled)
        except TimeoutError:
            # Stop waiting, never cancel the dispatcher's owned drain task.
            return JSONResponse(
                status_code=503,
                content={"op_id": envelope.op_id, "refused": "summary_wait_deadline"},
                headers={"Retry-After": "2"},
            )
        operation = await agent.store.observe(envelope.op_id)
        if operation is None:
            raise HTTPException(status_code=500, detail="summary attempt vanished")
        described = await _describe(agent, operation)
        if operation.state == "completed" and text is not None:
            described["summary"] = text
            return JSONResponse(described)
        return JSONResponse(
            status_code=502 if operation.state == "failed" else 503,
            content=described,
            headers={"Retry-After": "60"},
        )

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
        if batch.expected_manifest is not None and measured.identity != batch.expected_manifest:
            return _guard_refused(
                GuardRefusal(
                    "embedding_revision_mismatch", "embedding weights differ from the index space"
                )
            )
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
        """`load`, `unload`, `pull` or `repin`, with the node to itself (PR4b).

        A pull streams `accepted`, its progress and one `terminal` event, as
        an inference does; the others answer once they have settled. A repin
        is an operator's retry of the pin a pull could not set (#68 §3).
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
        if action == "repin" and wanted.manifest_digest is None:
            raise HTTPException(
                status_code=400, detail="a repin names the approved manifest_digest"
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
            measured = await _measure(agent, wanted.ref)
            pinned = check_pin(registered, measured.identity)
            if pinned is not None:
                return _guard_refused(pinned)
            if measured.declared_context is not None and context_length is not None:
                context_length = min(context_length, measured.declared_context)
        if action == "load":
            relay = agent.relay.load(
                wanted.ref, keep_alive=agent.keep_alive, context_length=context_length
            )
        elif action == "unload":
            relay = agent.relay.unload(wanted.ref)
        elif action == "repin":
            relay = _operator_repin(agent, wanted)
        else:
            relay = agent.relay.pull(wanted.ref)
        submitted = await agent.dispatcher.exclusive(
            wanted.op_id,
            action,
            relay,
            provenance={"ref": wanted.ref, "context_length": context_length},
            after=_repin(agent, wanted)
            if action == "pull"
            else (_record_capacity(agent, wanted.ref) if action in ("load", "repin") else None),
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

    @app.get("/v1/residency", dependencies=[Depends(_observer)])
    async def residency(request: Request) -> JSONResponse:
        """What the runtime holds and has on disk, read-only. Observing changes
        nothing, so it is answered whatever the gate says, and to either token:
        the maintenance coordinator snapshots and verifies with it (P4 on #61)."""
        observed = await _agent(request).relay.residency()
        if observed is None:
            return JSONResponse(status_code=503, content={"refused": "runtime_unobserved"})
        return JSONResponse(observed)

    @app.get("/v1/model-capacity", dependencies=authorised)
    async def model_capacity(
        request: Request, ref: str = Query(min_length=1, max_length=255)
    ) -> dict[str, Any]:
        """Metadata on this host. Reads remain available while dispatch is blocked."""
        measured = await _measure(_agent(request), ref)
        return {
            "manifest_digest": measured.identity,
            "declared_context_length": measured.declared_context,
            "embedding_manifest_pin": True,
        }

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

    @app.post("/v1/drain", dependencies=controlled)
    async def drain(request: Request) -> dict[str, Any]:
        agent = _agent(request)
        await agent.dispatcher.drain()
        return {"gate": agent.dispatcher.state.value, "admitted": agent.dispatcher.admitted}

    @app.post("/v1/resume", dependencies=controlled, response_model=None)
    async def resume(request: Request) -> dict[str, Any] | JSONResponse:
        agent = _agent(request)
        if not await agent.runtime_quiet_for_serving():
            return JSONResponse(status_code=409, content={"refused": "runtime_request_running"})
        state = await agent.dispatcher.reopen()
        return {"gate": state.value}

    @app.post("/v1/maintenance/resolutions", dependencies=controlled)
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

    @app.post("/v1/maintenance/resolutions/{resolution_id}/complete", dependencies=controlled)
    async def complete_resolution(request: Request, resolution_id: str) -> JSONResponse:
        try:
            done = await _agent(request).resolutions.complete(resolution_id)
        except ResolutionRefused as exc:
            return JSONResponse(status_code=409, content={"refused": str(exc)})
        return JSONResponse(done)

    @app.post("/v1/maintenance/resets", dependencies=controlled)
    async def reset(request: Request) -> JSONResponse:
        """Clear one block by a supervised restart (#49 §5): the resolution
        above, with the supervisor restarting the runtime between its two
        witness answers instead of an operator."""
        agent = _agent(request)
        body = await _body(request)
        op_id, operator = _text(body, "op_id", limit=128), _text(body, "operator", limit=128)
        evidence = _text(body, "evidence")
        try:
            done = await agent.resolutions.reset(
                op_id, evidence=evidence, operator=operator, supervisor=agent.supervisor
            )
        except ResolutionRefused as exc:
            return JSONResponse(status_code=409, content={"refused": str(exc)})
        return JSONResponse(done)

    @app.post("/v1/maintenance/interrupt", dependencies=controlled)
    async def interrupt(request: Request) -> JSONResponse:
        """Cancel every sender on this node for a closed maintenance hold (#61).

        Only for the hold the database says is closed, at the epoch named: an
        interrupt meant for one entry cannot land on the node after it reopened
        or during the next one. Cancelled attempts become `outcome_unknown` and
        block the node; a supervised restart is what can resolve them.
        """
        agent = _agent(request)
        body = await _body(request)
        epoch = body.get("epoch") if isinstance(body, dict) else None
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            raise HTTPException(status_code=400, detail="epoch must be an integer")
        closed, current = await agent.store.maintenance_hold()
        if not closed or current != epoch:
            return JSONResponse(
                status_code=409,
                content={"refused": "hold_not_closed_at_epoch", "closed": closed, "epoch": current},
            )
        await agent.dispatcher.freeze(epoch)
        report = await agent.dispatcher.interrupt(deadline_s=agent.settings.interrupt_deadline_s)
        await agent.store.audit("maintenance_interrupt", None, report)
        return JSONResponse(report | {"gate": agent.dispatcher.state.value})

    @app.post("/v1/maintenance/reset", dependencies=controlled)
    async def maintenance_reset(request: Request) -> JSONResponse:
        """Restart the runtime empty for a maintenance entry, and clear the
        unknowns the restart proves gone (P4 on #61).

        For the hold the database says is closed, at the epoch named, and only
        once no sender is left: the coordinator interrupts first. `reset_id`
        is the caller's and names the supervisor request too, so the same call
        repeated returns the same reset instead of restarting again.
        """
        agent = _agent(request)
        body = await _body(request)
        epoch = body.get("epoch") if isinstance(body, dict) else None
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            raise HTTPException(status_code=400, detail="epoch must be an integer")
        reset_id = _text(body, "reset_id", limit=32)
        if not RESET_ID.fullmatch(reset_id):
            raise HTTPException(status_code=400, detail="reset_id must be 32 lowercase hex")
        operator = _text(body, "operator", limit=128)
        closed, current = await agent.store.maintenance_hold()
        if not closed or current != epoch:
            return JSONResponse(
                status_code=409,
                content={"refused": "hold_not_closed_at_epoch", "closed": closed, "epoch": current},
            )
        await agent.dispatcher.freeze(epoch)
        if not agent.dispatcher.quiescent:
            return JSONResponse(status_code=409, content={"refused": "node_not_quiescent"})
        try:
            report = await agent.resolutions.maintenance_reset(
                epoch=epoch, reset_id=reset_id, operator=operator, supervisor=agent.supervisor
            )
        except SupervisorRefused as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "refused": "supervisor_unanswered",
                    "detail": str(exc),
                    "request_id": exc.request_id,
                },
            )
        except ResetFailed as exc:
            return JSONResponse(
                status_code=502,
                content={"refused": "restart_failed", "supervisor_receipt": exc.receipt},
            )
        except ResolutionRefused as exc:
            return JSONResponse(
                status_code=409, content={"refused": "hold_not_closed_at_epoch", "detail": str(exc)}
            )
        return JSONResponse(report | {"gate": agent.dispatcher.state.value})

    @app.post("/v1/maintenance/restore", dependencies=controlled)
    async def maintenance_restore(request: Request) -> JSONResponse:
        """Load a model saved by a maintenance entry back, or probe it (P5 on #61).

        The one way past a frozen gate, and only for the hold the database
        says is closed at the epoch named. The model must be registered on
        this node, the runtime must hold the weights the snapshot recorded,
        and the context must be the one it was loaded with: a restore puts
        back what was there, and refuses rather than load something else.
        """
        agent = _agent(request)
        body = await _body(request)
        epoch = body.get("epoch") if isinstance(body, dict) else None
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            raise HTTPException(status_code=400, detail="epoch must be an integer")
        op_id = _text(body, "op_id", limit=128)
        action = _text(body, "action", limit=16)
        if action not in RESTORE_KINDS:
            raise HTTPException(status_code=400, detail=f"action must be one of {RESTORE_KINDS}")
        name = _text(body, "name", limit=255)
        digest = body.get("digest") if isinstance(body.get("digest"), str) else None
        wanted_context = body.get("context_length")
        if wanted_context is not None and (
            not isinstance(wanted_context, int) or isinstance(wanted_context, bool)
        ):
            raise HTTPException(status_code=400, detail="context_length must be an integer")

        closed, current = await agent.store.maintenance_hold()
        if not closed or current != epoch:
            return JSONResponse(
                status_code=409,
                content={"refused": "hold_not_closed_at_epoch", "closed": closed, "epoch": current},
            )
        existing = await agent.store.observe(op_id)
        if existing is not None:
            return await _existing_lifecycle(agent, existing, action)

        ref, registered = None, None
        for candidate in _spellings(name):
            registered = await registration(agent.pool, agent.settings.node_id, RUNTIME, candidate)
            if registered is not None:
                ref = candidate
                break
        if registered is None or ref is None:
            return _guard_refused(
                GuardRefusal("model_not_on_node", f"{name} is not registered on this node")
            )
        measured = await _measure(agent, ref)
        if digest is not None and measured.identity != digest:
            return _guard_refused(
                GuardRefusal(
                    "revision_mismatch",
                    f"the snapshot held {digest}, the runtime has {measured.identity}",
                )
            )
        pinned = check_pin(registered, measured.identity)
        if pinned is not None:
            return _guard_refused(pinned)
        context_length = registered.context_length or None
        if measured.declared_context is not None and context_length is not None:
            context_length = min(context_length, measured.declared_context)
        if wanted_context is not None and context_length not in (None, wanted_context):
            return _guard_refused(
                GuardRefusal(
                    "context_length_mismatch",
                    f"the snapshot loaded {wanted_context}, the registration gives "
                    f"{context_length}",
                )
            )
        context_length = wanted_context or context_length

        if action == "load":
            relay = agent.relay.load(
                ref, keep_alive=agent.keep_alive, context_length=context_length
            )
        else:
            relay = agent.relay.probe(
                ref,
                embedding="embedding" in registered.capabilities,
                keep_alive=agent.keep_alive,
                context_length=context_length,
            )
        submitted = await agent.dispatcher.exclusive(
            op_id,
            action,
            relay,
            provenance={
                "ref": ref,
                "context_length": context_length,
                "maintenance_epoch": epoch,
                "restore": True,
            },
            after=_record_capacity(agent, ref) if action == "load" else None,
            maintenance_epoch=epoch,
        )
        if isinstance(submitted, Existing):
            return await _existing_lifecycle(agent, submitted.operation, action)
        if isinstance(submitted, Refused):
            return JSONResponse(status_code=409, content={"refused": submitted.reason})
        await submitted.settled
        operation = await agent.store.observe(op_id)
        if operation is None:
            raise HTTPException(status_code=500, detail="operation vanished")
        return await _existing_lifecycle(agent, operation, action)

    @app.post("/v1/maintenance/runtime/{action}", dependencies=controlled)
    async def runtime_control(request: Request, action: str) -> JSONResponse:
        """Stop, start or restart the host runtime through the supervisor.

        Refused while the node serves or while any sender is still talking to
        the runtime: a restart under live traffic would only make unknowns.
        Freeze (a maintenance hold) or drain first. The receipt is the answer,
        and is recorded in the node's audit whether it says the action worked
        or not.
        """
        agent = _agent(request)
        if action not in SUPERVISOR_ACTIONS:
            raise HTTPException(
                status_code=404, detail=f"action must be one of {SUPERVISOR_ACTIONS}"
            )
        body = await _body(request)
        operator, reason = _text(body, "operator", limit=128), _text(body, "reason", limit=200)
        gate = agent.dispatcher.state
        if gate in (GateState.SERVING, GateState.LOST) or not agent.dispatcher.quiescent:
            return JSONResponse(
                status_code=409,
                content={
                    "refused": "node_not_quiescent",
                    "gate": gate.value,
                    "quiescent": agent.dispatcher.quiescent,
                },
            )
        await agent.store.audit(
            "runtime_control_requested",
            None,
            {"action": action, "operator": operator, "reason": reason},
        )
        try:
            receipt = await agent.supervisor.run(action, f"{operator}: {reason}")
        except SupervisorRefused as exc:
            await agent.store.audit(
                "runtime_control_unanswered",
                None,
                {
                    "action": action,
                    "operator": operator,
                    "error": str(exc),
                    "request_id": exc.request_id,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "refused": "supervisor_unanswered",
                    "detail": str(exc),
                    "request_id": exc.request_id,
                },
            )
        await agent.store.audit("runtime_control_receipt", None, receipt)
        return JSONResponse(
            status_code=200 if receipt.get("result") == "ok" else 502, content=receipt
        )

    @app.get("/v1/maintenance/runtime/receipts/{request_id}", dependencies=controlled)
    async def runtime_receipt(request: Request, request_id: str) -> JSONResponse:
        receipt = _agent(request).supervisor.receipt(request_id)
        if receipt is None:
            return JSONResponse(status_code=404, content={"request_id": request_id})
        return JSONResponse(receipt)

    return app


def _spellings(name: str) -> list[str]:
    """`/api/ps` names a model with its tag; a registration may not."""
    spellings = [name]
    if name.endswith(":latest"):
        spellings.append(name.removesuffix(":latest"))
    elif ":" not in name:
        spellings.append(f"{name}:latest")
    return spellings


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
    revision mismatch until an operator re-pins (`_operator_repin`, #68 §3):
    closed, not open."""

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
        await _record_capacity(agent, wanted.ref)(outcome)

    return after


def _operator_repin(agent: Agent, wanted: LifecycleRequest) -> Relay:
    """Pin the weights an operator approved, if they are what is served (#68 §3).

    The retry for a pull whose own re-pin did not happen, which otherwise
    leaves every load and dispatch refused as a revision mismatch. The
    operator names the digest; the agent pins it only when the runtime's
    listing and the model store both report exactly that digest, read inside
    the exclusive operation so nothing is dispatched against weights that
    changed in between. Anything less is refused and the pin stays as it was:
    closed, as after the failed pull. Nothing is sent to the runtime, so no
    outcome here is uncertain.
    """
    approved = wanted.manifest_digest

    async def run(sink: Sink) -> Outcome:
        evidence: dict[str, Any] = {"approved": approved}
        try:
            served = await agent.relay.served_digest(wanted.ref)
        except Exception as exc:  # noqa: BLE001 - cannot confirm is a refusal, not a match
            return RuntimeRefused(
                terminal=evidence, reason=f"revision_unconfirmed:{type(exc).__name__}"
            )
        measured = await _measure(agent, wanted.ref)
        evidence |= {"served": served, "measured": measured.identity}
        if served is None:
            return RuntimeRefused(terminal=evidence, reason="not_listed")
        if approved is None or served != approved or measured.identity != approved:
            return RuntimeRefused(terminal=evidence, reason="digest_mismatch")
        try:
            moved = await agent.store.repin(wanted.op_id, RUNTIME, wanted.ref, approved)
        except Exception:  # noqa: BLE001 - the pin stays; the operator may retry
            logger.exception("could not write the approved pin for %s", wanted.ref)
            return RuntimeRefused(terminal=evidence, reason="pin_not_written")
        try:
            await agent.store.audit(
                "repin",
                wanted.op_id,
                {"ref": wanted.ref, "digest": approved, "models": moved, "by": "operator"},
            )
        except Exception:  # noqa: BLE001 - the admin's audit row still records it
            logger.exception("could not record the operator's repin of %s", wanted.ref)
        return Completed(terminal=evidence | {"models": moved})

    return run


def _record_capacity(agent: Agent, ref: str) -> Callable[[Outcome], Awaitable[None]]:
    async def after(outcome: Outcome) -> None:
        if not isinstance(outcome, Completed):
            return
        measured = await _measure(agent, ref)
        # A replacement manifest must not validate a row pinned to older weights.
        # Reads and writes remain scoped to this agent's node and runtime.
        async with agent.pool.acquire() as connection:
            await connection.execute(
                "UPDATE models SET capacity_validated = $4 "
                "WHERE node_id = $1 AND runtime = $2 AND ref = $3 "
                "AND (manifest_digest IS NULL OR manifest_digest = $5)",
                agent.settings.node_id,
                RUNTIME,
                ref,
                measured.declared_context is not None,
                measured.identity,
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
