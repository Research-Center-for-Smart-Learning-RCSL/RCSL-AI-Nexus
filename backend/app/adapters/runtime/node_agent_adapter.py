"""A runtime reached through its node's agent (PR4a-2 on #24).

Implements `ModelRuntimePort` by calling the agent of one node, so every
caller that already goes through the port reaches the runtime through the
agent without changing. Which methods it serves depends on the stage (design
R4); the rest fail closed with `RuntimeCapabilityError`, never by reaching the
runtime some other way:

| method | 4a | 4b | 4c |
|---|---|---|---|
| `generate`, `embed` | agent | agent | agent |
| `validate_ref` | in-process grammar | same | same |
| `health` | agent status | same | same |
| `load`, `unload`, `pull`, `residency` | refused | agent (this stage) | agent + reconciler |

The agent relays the runtime's own lines; they are decoded here by the same
`ChatStreamDecoder` the direct adapter uses. Request identity comes from
`current_attempt`, set by the caller that bound the request; without one, the
call is an unbound attempt that no client can repeat.

Transport rules (final spec §5): a connection that could not be made is
retried once **with the same op id**, which the agent treats idempotently; a
stream that breaks after the agent accepted it is an interruption, never a
retry, and never spliced with output from anywhere else.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.adapters.runtime.ollama_adapter.decoding import ChatStreamDecoder
from app.adapters.runtime.ollama_adapter.lifecycle import residency_from
from app.domain.entities.attempt import AttemptIdentity, current_attempt
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import PullProgress, RuntimeResidency
from app.domain.exceptions import (
    ModelNotFoundError,
    NoAvailableModelError,
    RuntimeCapabilityError,
    ServerOverloadedError,
    StreamInterruptedError,
)
from app.domain.ports.request_binding_port import AttemptView
from app.node_agent.wire import (
    EmbeddingRequest,
    Envelope,
    GenerationRequest,
    LifecycleRequest,
    encode_embedding,
    encode_generation,
    encode_lifecycle,
)

logger = logging.getLogger(__name__)


class NodeAgentRuntime:
    def __init__(
        self,
        agent_url: str,
        token: str,
        *,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = agent_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._transport = transport
        # Grammar only, no I/O: what a reference is does not depend on who sends.
        self._grammar = OllamaAdapter(base_url="http://unused.invalid")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._url,
            headers=self._headers,
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _identity() -> AttemptIdentity:
        return current_attempt.get() or AttemptIdentity.unbound()

    @staticmethod
    def _envelope(identity: AttemptIdentity) -> Envelope:
        return Envelope(
            op_id=identity.op_id,
            request_id=identity.request_id,
            payload_hash=identity.payload_hash,
            store_output=identity.store_output,
        )

    # -- generation --------------------------------------------------------

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.validate_ref(ref)
        if not context_length or not max_tokens:
            # The agent checks the request against its registration and the
            # output reserve; it is never sent a request that says neither.
            raise RuntimeCapabilityError(
                detail=f"{ref}: the node agent needs a registered context and an output bound"
            )
        identity = self._identity()
        body = encode_generation(
            GenerationRequest(
                ref=ref,
                messages=tuple(messages),
                max_tokens=max_tokens,
                thinking=thinking,
                tools=tuple(tools),
                tool_choice=tool_choice,
                sampling=sampling,
                context_length=context_length,
            ),
            self._envelope(identity),
        )
        decoder = ChatStreamDecoder(ref)
        emitted = False
        async with self._client() as client:
            response = await self._open_stream(client, body, identity.op_id)
            try:
                if response.headers.get("content-type", "").startswith("application/json"):
                    await response.aread()
                    for replayed in self._replay(ref, response.json()):
                        yield replayed
                    return
                terminal: dict[str, Any] | None = None
                try:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        kind = event.get("type")
                        if kind == "line":
                            data = event.get("data") or {}
                            if data.get("error"):
                                continue  # the terminal event carries the outcome
                            chunk = decoder.decode(data)
                            if chunk is not None:
                                emitted = True
                                yield chunk
                        elif kind == "terminal":
                            terminal = event
                except (httpx.HTTPError, json.JSONDecodeError) as exc:
                    raise StreamInterruptedError(
                        detail=f"node agent stream for {identity.op_id} broke: {exc!r}"
                    ) from exc
                self._settle(identity.op_id, terminal, decoder, emitted)
            finally:
                await response.aclose()

    async def _open_stream(
        self, client: httpx.AsyncClient, body: dict[str, Any], op_id: str
    ) -> httpx.Response:
        for attempt in (1, 2):
            try:
                request = client.build_request("POST", "/v1/inference", json=body)
                response = await client.send(request, stream=True)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 2:
                    raise NoAvailableModelError(
                        detail=f"node agent unreachable for {op_id}: {exc!r}"
                    ) from exc
                logger.info("node agent connect failed for %s; resending the same op id", op_id)
                continue
            except httpx.HTTPError as exc:
                # Something may have reached the agent. The same op id is
                # never sent again from here; the attempt is the caller's to
                # look up.
                raise StreamInterruptedError(
                    detail=f"node agent request for {op_id} failed after sending: {exc!r}"
                ) from exc
            if response.status_code == 200:
                return response
            await response.aread()
            await response.aclose()
            self._raise_for_refusal(response, op_id)
        raise NoAvailableModelError(detail=f"node agent gave no response for {op_id}")

    def _raise_for_refusal(self, response: httpx.Response, op_id: str) -> None:
        try:
            content = response.json()
        except ValueError:
            content = {}
        reason = content.get("refused") or content.get("detail") or response.text[:200]
        if response.status_code == 503:
            retry = response.headers.get("retry-after")
            raise ServerOverloadedError(
                retry_after_seconds=int(retry) if retry and retry.isdigit() else 60,
                detail=f"node agent refused {op_id}: {reason}",
            )
        if response.status_code == 401:
            logger.error("node agent rejected this entrance's token")
        raise NoAvailableModelError(
            detail=f"node agent answered {response.status_code} for {op_id}: {reason}"
        )

    def _settle(
        self,
        op_id: str,
        terminal: dict[str, Any] | None,
        decoder: ChatStreamDecoder,
        emitted: bool,
    ) -> None:
        if terminal is None:
            raise StreamInterruptedError(detail=f"node agent stream for {op_id} ended early")
        state = terminal.get("state")
        if state == "completed" and decoder.saw_done:
            return
        if state == "failed":
            raise NoAvailableModelError(detail=f"runtime failed {op_id}: {terminal.get('reason')}")
        raise StreamInterruptedError(
            detail=f"{op_id} ended {state} ({terminal.get('reason')}); output emitted={emitted}"
        )

    def _replay(self, ref: str, described: dict[str, Any]) -> list[CompletionChunk]:
        """An existing attempt met by a POST: its stored result, or a refusal."""
        view = _view(described)
        if view.state == "completed":
            if view.result is None:
                # Decision Q2: nothing was stored without a key. Never run
                # again; say what happened instead.
                raise StreamInterruptedError(
                    detail=f"{view.op_id} completed but its result was not retained"
                )
            return self.replay(ref, view)
        if view.state == "failed":
            raise NoAvailableModelError(detail=f"{view.op_id} failed: {view.reason}")
        raise StreamInterruptedError(detail=f"{view.op_id} is {view.state}; it is not run again")

    # -- the attempt ledger (AttemptLedgerPort) ----------------------------

    async def describe(self, op_id: str) -> AttemptView | None:
        try:
            async with self._client() as client:
                response = await client.get(f"/v1/attempts/{op_id}")
        except httpx.HTTPError as exc:
            raise NoAvailableModelError(
                detail=f"node agent unreachable describing {op_id}: {exc!r}"
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._raise_for_refusal(response, op_id)
        return _view(response.json())

    async def cancel(self, op_id: str, kind: str) -> AttemptView:
        try:
            async with self._client() as client:
                response = await client.post(f"/v1/attempts/{op_id}/cancel", params={"kind": kind})
        except httpx.HTTPError as exc:
            raise NoAvailableModelError(
                detail=f"node agent unreachable cancelling {op_id}: {exc!r}"
            ) from exc
        if response.status_code != 200:
            self._raise_for_refusal(response, op_id)
        return _view(response.json())

    def replay(self, ref: str, view: AttemptView) -> list[CompletionChunk]:
        """Decision Q3: one chunk carrying the whole content, reasoning and
        tool calls, then the original finish reason and totals."""
        result = view.result or {}
        decoder = ChatStreamDecoder(ref)
        chunk = decoder.decode(
            {
                "message": {
                    "role": "assistant",
                    "content": result.get("content") or "",
                    "thinking": result.get("thinking") or "",
                    "tool_calls": result.get("tool_calls") or [],
                },
                "done": True,
                "done_reason": result.get("done_reason"),
                "eval_count": result.get("eval_count"),
                "prompt_eval_count": result.get("prompt_eval_count"),
            }
        )
        return [chunk] if chunk is not None else []

    # -- embeddings --------------------------------------------------------

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        self.validate_ref(ref)
        identity = self._identity()
        body = encode_embedding(
            EmbeddingRequest(ref=ref, texts=tuple(texts)), self._envelope(identity)
        )
        async with self._client() as client:
            response: httpx.Response | None = None
            for attempt in (1, 2):
                try:
                    response = await client.post("/v1/embeddings", json=body)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    if attempt == 2:
                        raise NoAvailableModelError(
                            detail=f"node agent unreachable for {identity.op_id}: {exc!r}"
                        ) from exc
                except httpx.HTTPError as exc:
                    raise StreamInterruptedError(
                        detail=f"embedding {identity.op_id} failed after sending: {exc!r}"
                    ) from exc
        assert response is not None  # noqa: S101 - the loop either breaks or raises
        if response.status_code != 200:
            self._raise_for_refusal(response, identity.op_id)
        described = response.json()
        # A fresh batch carries its vectors at the top; a repeated op id
        # carries the stored result under `result` (review of #33's branch).
        stored = described.get("result")
        vectors = described.get("embeddings")
        if vectors is None and isinstance(stored, dict):
            vectors = stored.get("embeddings")
        if described.get("state") != "completed" or not isinstance(vectors, list):
            raise NoAvailableModelError(
                detail=f"embedding {identity.op_id} is {described.get('state')} with no vectors"
            )
        return [[float(v) for v in vector] for vector in vectors]

    # -- the rest of the port ----------------------------------------------

    def validate_ref(self, ref: str) -> None:
        self._grammar.validate_ref(ref)

    async def runtime_version(self) -> str | None:
        """The runtime's version as the agent reads it now (PR2b)."""
        try:
            async with self._client() as client:
                response = await client.get("/v1/status")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        version = response.json().get("runtime_version")
        return version if isinstance(version, str) and version else None

    async def health(self) -> bool:
        try:
            async with self._client() as client:
                response = await client.get("/v1/status")
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and response.json().get("gate") == "serving"

    # -- lifecycle (PR4b) --------------------------------------------------

    async def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """The agent's pull, which has the node to itself while it runs.

        Progress arrives as the agent reads it; the terminal event says
        whether the pull completed, and only then does this return normally.
        """
        self.validate_ref(ref)
        op_id = str(uuid.uuid4())
        body = encode_lifecycle(LifecycleRequest(op_id=op_id, ref=ref, context_length=None))
        async with self._client() as client:
            response = await self._send_lifecycle(client, "pull", body, op_id, stream=True)
            try:
                if response.headers.get("content-type", "").startswith("application/json"):
                    await response.aread()
                    self._lifecycle_outcome("pull", ref, op_id, response.json())
                    return
                terminal: dict[str, Any] | None = None
                try:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get("type") == "progress":
                            yield PullProgress(
                                status=str(event.get("status") or ""),
                                completed_bytes=event.get("completed"),
                                total_bytes=event.get("total"),
                            )
                        elif event.get("type") == "terminal":
                            terminal = event
                except (httpx.HTTPError, json.JSONDecodeError) as exc:
                    raise StreamInterruptedError(
                        detail=f"node agent pull {op_id} broke: {exc!r}"
                    ) from exc
                self._lifecycle_outcome("pull", ref, op_id, terminal)
            finally:
                await response.aclose()

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        await self._lifecycle("load", ref, context_length)

    async def unload(self, ref: str) -> None:
        await self._lifecycle("unload", ref, None)

    async def residency(self) -> RuntimeResidency | None:
        """None when the agent or its runtime cannot be asked, never "empty"."""
        try:
            async with self._client() as client:
                response = await client.get("/v1/residency")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            document = response.json()
            return residency_from(document["resident"], document["on_disk"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    async def _lifecycle(self, action: str, ref: str, context_length: int | None) -> None:
        self.validate_ref(ref)
        op_id = str(uuid.uuid4())
        body = encode_lifecycle(
            LifecycleRequest(op_id=op_id, ref=ref, context_length=context_length)
        )
        async with self._client() as client:
            response = await self._send_lifecycle(client, action, body, op_id, stream=False)
            await response.aread()
        self._lifecycle_outcome(action, ref, op_id, response.json())

    async def _send_lifecycle(
        self,
        client: httpx.AsyncClient,
        action: str,
        body: dict[str, Any],
        op_id: str,
        *,
        stream: bool,
    ) -> httpx.Response:
        """One connect retry with the same op id, which the agent treats as the
        same operation; nothing after the request may have left is resent."""
        for attempt in (1, 2):
            try:
                request = client.build_request("POST", f"/v1/lifecycle/{action}", json=body)
                response = await client.send(request, stream=stream)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 2:
                    raise NoAvailableModelError(
                        detail=f"node agent unreachable for {action} {op_id}: {exc!r}"
                    ) from exc
                continue
            except httpx.HTTPError as exc:
                raise StreamInterruptedError(
                    detail=f"{action} {op_id} failed after sending: {exc!r}"
                ) from exc
            if response.status_code in (200, 202, 502):
                return response
            await response.aread()
            await response.aclose()
            if response.status_code == 422:
                raise RuntimeCapabilityError(
                    detail=f"node agent refused {action} {op_id}: {response.text[:200]}"
                )
            self._raise_for_refusal(response, op_id)
        raise NoAvailableModelError(detail=f"node agent gave no response for {op_id}")

    @staticmethod
    def _lifecycle_outcome(
        action: str, ref: str, op_id: str, described: dict[str, Any] | None
    ) -> None:
        if described is None:
            raise StreamInterruptedError(detail=f"{action} {op_id} of {ref} ended early")
        state = described.get("state")
        if state == "completed":
            return
        reason = described.get("reason")
        if state == "failed" and reason == "not_found":
            raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
        if state == "failed":
            raise NoAvailableModelError(detail=f"{action} of {ref} failed ({reason}), {op_id}")
        raise StreamInterruptedError(detail=f"{action} {op_id} of {ref} is {state} ({reason})")


def _view(described: dict[str, Any]) -> AttemptView:
    result = described.get("result")
    reason = described.get("reason")
    return AttemptView(
        op_id=str(described.get("op_id")),
        state=str(described.get("state")),
        reason=reason if isinstance(reason, str) else None,
        result=result if isinstance(result, dict) else None,
    )
