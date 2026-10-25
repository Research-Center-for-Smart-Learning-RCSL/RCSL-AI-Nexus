"""The agent's sends to an Ollama runtime, read to terminal evidence.

Every relay reports an `Outcome` the dispatcher settles from, and the
classification is the part that matters (design Q5, R5, U2 on #24):

- **Completed** only on the runtime's own terminal evidence: the `done: true`
  line of a stream, or the response of a call. Its figures are the runtime's
  raw totals, never a chunk sum corrected after the fact.
- **RuntimeRefused** when the runtime answered with an error status or an
  error line: it said the request ended.
- **NotSent** only for `httpx.ConnectError` or `ConnectTimeout` on the
  attempt's single transport try, the one failure httpx raises before any
  request byte is written. The transport has retries disabled, so nothing
  earlier could have sent it.
- **Uncertain** for everything else after that point: a read error or
  timeout, a protocol error, EOF without `done`. These block the node. A
  summary's shorter idle bound between lines is such a read timeout: it
  ends the wait sooner, not the uncertainty.

A stream is read to its end whatever happens to the caller. The replay buffer
is bounded; past the bound the output is discarded and the attempt is marked
replay-unavailable, and reading continues to `done`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.runtime.ollama_adapter.encoding import _set_num_ctx
from app.node_agent.dispatch import (
    Completed,
    NotSent,
    Outcome,
    Relay,
    RuntimeRefused,
    Sink,
    Uncertain,
)

logger = logging.getLogger(__name__)

REPLAY_CAP_BYTES = 4 * 1024 * 1024
CHECKPOINT_SECONDS = 5.0
SUMMARY_IDLE_SECONDS = 120.0
"""Longest gap between two lines of a summary stream once it has started.

A token on a 7B model arrives in tens of milliseconds, and in seconds even
under memory pressure, so two minutes is only reached by a stall. It bounds
how long a stalled runtime holds the node's one summary slot, which the
request timeout (25 minutes per read) otherwise would. The first line, after
any cold load and the prefill, still waits on the request timeout.
"""
_TERMINAL_FIELDS = (
    "done_reason",
    "eval_count",
    "prompt_eval_count",
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)


class _IdleTimeout(Exception):
    """No line arrived within the idle bound after the stream had started."""


async def _idle_bounded(lines: AsyncIterator[str], idle_s: float | None) -> AsyncIterator[str]:
    """`lines`, with each read after the first bounded by `idle_s`.

    The first line waits on the client's own read timeout: a cold load and the
    prefill both happen before the runtime sends anything. Once it streams, a
    gap is between two generated tokens, so a short bound only cuts a stall.
    Only the wait for a line is timed, never the consumer's handling of it.
    """
    started = False
    while True:
        try:
            if started and idle_s is not None:
                try:
                    async with asyncio.timeout(idle_s):
                        line = await anext(lines)
                except TimeoutError as exc:
                    raise _IdleTimeout from exc
            else:
                line = await anext(lines)
        except StopAsyncIteration:
            return
        started = True
        yield line


def _tag(ref: str) -> str:
    """`/api/tags` names a model with its tag, `latest` included."""
    return ref if ":" in ref.rsplit("/", 1)[-1] else f"{ref}:latest"


PROBE_TOKENS = 16
"""Enough for a thinking model to produce something, bounded so the check is a
check and not a generation."""

PROBE_TIMEOUT_S = 120.0


class LifecycleRelay:
    """Lifecycle sends: the same requests the direct adapter made (PR4b).

    A base of `OllamaRelay` rather than a separate client so the agent has one
    client and one transport to its runtime. Classified like every other
    send; the dispatcher decides what an uncertain one means.
    """

    _client: httpx.AsyncClient

    def load(self, ref: str, *, keep_alive: str | int, context_length: int | None) -> Relay:
        return self._lifecycle(ref, keep_alive=keep_alive, context_length=context_length)

    def unload(self, ref: str) -> Relay:
        return self._lifecycle(ref, keep_alive=0, context_length=None)

    def _lifecycle(self, ref: str, *, keep_alive: str | int, context_length: int | None) -> Relay:
        # The load is where the runtime sizes the runner, so it carries the
        # registered context; an unload sizes nothing (`lifecycle.py`).
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        body: dict[str, Any] = {"model": ref, "keep_alive": keep_alive}
        if options:
            body["options"] = options

        async def run(sink: Sink) -> Outcome:
            try:
                response = await self._client.post("/api/generate", json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                return NotSent(type(exc).__name__)
            except httpx.HTTPError as exc:
                return Uncertain(f"transport:{type(exc).__name__}")
            endpoint = "generate"
            if response.status_code == 400:
                # An embedding model refuses generate; an empty embed moves the
                # same weights the same way.
                endpoint = "embed"
                try:
                    response = await self._client.post("/api/embed", json={**body, "input": []})
                except httpx.HTTPError as exc:
                    return Uncertain(f"transport:{type(exc).__name__}")
            terminal = {"status": response.status_code, "endpoint": endpoint}
            if response.status_code == 404:
                return RuntimeRefused(terminal=terminal, reason="not_found")
            if response.status_code >= 400:
                terminal["error"] = response.text[:500]
                return RuntimeRefused(terminal=terminal, reason=f"http_{response.status_code}")
            return Completed(terminal=terminal)

        return run

    def probe(
        self, ref: str, *, embedding: bool, keep_alive: str | int, context_length: int | None
    ) -> Relay:
        """The bounded functional check a restore runs on each model (P5 on
        #61): a load that answered 200 says the weights moved, not that the
        model answers. An embedding model must return a non-empty vector; any
        other must generate at least one token. Sized with the context the
        model was loaded with, so the check cannot itself reload it."""
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        body: dict[str, Any] = {"model": ref, "keep_alive": keep_alive}
        if embedding:
            path = "/api/embed"
            body["input"] = ["maintenance restore probe"]
        else:
            path = "/api/generate"
            options["num_predict"] = PROBE_TOKENS
            body |= {"prompt": "Reply with the single word: ready", "stream": False}
        if options:
            body["options"] = options

        async def run(sink: Sink) -> Outcome:
            try:
                response = await self._client.post(path, json=body, timeout=PROBE_TIMEOUT_S)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                return NotSent(type(exc).__name__)
            except httpx.HTTPError as exc:
                return Uncertain(f"transport:{type(exc).__name__}")
            terminal: dict[str, Any] = {"status": response.status_code, "endpoint": path}
            if response.status_code >= 400:
                terminal["error"] = response.text[:500]
                return RuntimeRefused(terminal=terminal, reason=f"http_{response.status_code}")
            try:
                answer = response.json()
            except ValueError:
                return RuntimeRefused(terminal=terminal, reason="probe_unreadable")
            if not isinstance(answer, dict):
                return RuntimeRefused(terminal=terminal, reason="probe_unreadable")
            if embedding:
                vectors = answer.get("embeddings")
                width = len(vectors[0]) if isinstance(vectors, list) and vectors else 0
                if not width:
                    return RuntimeRefused(terminal=terminal, reason="probe_no_vector")
                return Completed(terminal=terminal | {"dimensions": width})
            generated = int(answer.get("eval_count") or 0)
            if not answer.get("done") or generated <= 0:
                return RuntimeRefused(terminal=terminal, reason="probe_no_tokens")
            return Completed(terminal=terminal | {"eval_count": generated})

        return run

    def pull(self, ref: str) -> Relay:
        async def run(sink: Sink) -> Outcome:
            last: dict[str, Any] = {}
            try:
                async with self._client.stream(
                    "POST", "/api/pull", json={"model": ref, "stream": True}
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread())[:500].decode("utf-8", "replace")
                        return RuntimeRefused(
                            terminal={"status": response.status_code, "error": body},
                            reason="not_found"
                            if response.status_code == 404
                            else f"http_{response.status_code}",
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if event.get("error"):
                            return RuntimeRefused(
                                terminal={"error": str(event["error"])[:500]},
                                reason="runtime_error",
                            )
                        last = {
                            "status": event.get("status", ""),
                            "completed": event.get("completed"),
                            "total": event.get("total"),
                        }
                        sink.emit({"type": "progress", **last})
                        if event.get("status") == "success":
                            return Completed(terminal={"status": "success"})
                    return Uncertain("eof_without_success", last)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                return NotSent(type(exc).__name__)
            except httpx.HTTPError as exc:
                return Uncertain(f"transport:{type(exc).__name__}", last)

        return run

    async def residency(self) -> dict[str, Any] | None:
        """`/api/ps` and `/api/tags`, read-only, or None when either fails:
        "could not ask" must not read as "nothing is loaded" (`lifecycle.py`)."""
        try:
            ps = await self._client.get("/api/ps", timeout=10.0)
            tags = await self._client.get("/api/tags", timeout=10.0)
            if ps.status_code != 200 or tags.status_code != 200:
                return None
            return {
                "resident": ps.json().get("models") or [],
                "on_disk": tags.json().get("models") or [],
            }
        except (httpx.HTTPError, ValueError):
            return None


class OllamaRelay(LifecycleRelay):
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float,
        replay_cap_bytes: int = REPLAY_CAP_BYTES,
        checkpoint_s: float = CHECKPOINT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            # One try. A transport retry could re-send a request whose first
            # attempt reached the runtime, and would make "connect failed"
            # stop meaning "never sent".
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
        )
        self._replay_cap = replay_cap_bytes
        self._checkpoint_s = checkpoint_s

    async def aclose(self) -> None:
        await self._client.aclose()

    async def served_digest(self, ref: str) -> str | None:
        """The manifest digest the runtime reports for `ref`, read-only.

        Raises `httpx.HTTPError` when the runtime cannot be asked; the caller
        treats that as "cannot confirm the revision", never as a match.
        """
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        wanted = _tag(ref)
        for model in response.json().get("models", []):
            if model.get("name") == wanted or model.get("model") == wanted:
                digest = model.get("digest")
                return digest if isinstance(digest, str) else None
        return None

    async def health(self) -> bool:
        return await self.version() is not None

    async def version(self) -> str | None:
        """What the runtime says it is, read now; None when it cannot say."""
        try:
            response = await self._client.get("/api/version", timeout=5.0)
            if response.status_code != 200:
                return None
            version = response.json().get("version")
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        return version if isinstance(version, str) and version else None

    def chat(
        self,
        payload: dict[str, Any],
        *,
        store_output: bool,
        expected_identity: str | None,
        idle_timeout_s: float | None = None,
    ) -> Relay:
        async def run(sink: Sink) -> Outcome:
            mismatch = await self._revision_mismatch(payload["model"], expected_identity)
            if mismatch is not None:
                return mismatch
            return await self._stream_chat(
                payload, sink, store_output=store_output, idle_timeout_s=idle_timeout_s
            )

        return run

    def embed(
        self, payload: dict[str, Any], *, store_output: bool, expected_identity: str | None
    ) -> Relay:
        async def run(sink: Sink) -> Outcome:
            mismatch = await self._revision_mismatch(payload["model"], expected_identity)
            if mismatch is not None:
                return mismatch
            return await self._embed(payload, sink, store_output=store_output)

        return run

    async def _revision_mismatch(self, ref: str, expected: str | None) -> Outcome | None:
        """Refuse, before sending, weights other than the ones the guard measured.

        Design S5: the guard counted against one manifest; the runtime resolves
        the tag itself. A tag rewritten after this read and before the runtime
        resolves it is the documented detection-only window.
        """
        if expected is None:
            return None
        try:
            served = await self.served_digest(ref)
        except httpx.HTTPError as exc:
            return NotSent(f"revision_unconfirmed:{type(exc).__name__}")
        if served != expected:
            logger.warning("%s is served as %s, measured as %s; not sending", ref, served, expected)
            return NotSent("revision_mismatch")
        return None

    async def _stream_chat(
        self,
        payload: dict[str, Any],
        sink: Sink,
        *,
        store_output: bool,
        idle_timeout_s: float | None = None,
    ) -> Outcome:
        started = time.monotonic()
        last_checkpoint = started
        chunks = 0
        replay: dict[str, Any] = {"content": [], "thinking": [], "tool_calls": []}
        replay_bytes = 0
        overflowed = False

        def observed() -> dict[str, Any]:
            # Observations, never called tokens (design U2).
            return {
                "observed_chunk_count": chunks,
                "observed_elapsed_ms": int((time.monotonic() - started) * 1000),
            }

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread())[:500].decode("utf-8", "replace")
                    return RuntimeRefused(
                        terminal={"status": response.status_code, "error": body},
                        reason=f"http_{response.status_code}",
                    )
                async for line in _idle_bounded(response.aiter_lines(), idle_timeout_s):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        # The adapter ignores these too; the stream goes on.
                        logger.warning("ollama emitted a non-JSON line, ignoring")
                        continue
                    sink.emit({"type": "line", "data": event})
                    if event.get("error"):
                        return RuntimeRefused(
                            terminal={"error": str(event["error"])[:500], **observed()},
                            reason="runtime_error",
                        )
                    message = event.get("message") or {}
                    if store_output and not overflowed:
                        piece = (
                            len((message.get("content") or "").encode())
                            + len((message.get("thinking") or "").encode())
                            + len(json.dumps(message.get("tool_calls") or []))
                        )
                        if replay_bytes + piece > self._replay_cap:
                            overflowed = True
                            replay = {}
                        else:
                            replay_bytes += piece
                            replay["content"].append(message.get("content") or "")
                            replay["thinking"].append(message.get("thinking") or "")
                            replay["tool_calls"].extend(message.get("tool_calls") or [])
                    if event.get("done"):
                        terminal = {k: event.get(k) for k in _TERMINAL_FIELDS} | observed()
                        result = None
                        if store_output and not overflowed:
                            result = {
                                "content": "".join(replay["content"]),
                                "thinking": "".join(replay["thinking"]),
                                "tool_calls": replay["tool_calls"],
                                **{k: event.get(k) for k in _TERMINAL_FIELDS},
                            }
                        return Completed(
                            terminal=terminal,
                            result=result,
                            replay_unavailable=store_output and overflowed,
                        )
                    chunks += 1
                    if time.monotonic() - last_checkpoint >= self._checkpoint_s:
                        last_checkpoint = time.monotonic()
                        await sink.checkpoint(observed())
                return Uncertain("eof_without_done", observed())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return NotSent(type(exc).__name__)
        except httpx.HTTPError as exc:
            return Uncertain(f"transport:{type(exc).__name__}", observed())
        except _IdleTimeout:
            # Stopped reading, not seen to end: the runtime may still be
            # generating, so this is a transport timeout like any other.
            return Uncertain("transport:IdleTimeout", observed())

    async def _embed(self, payload: dict[str, Any], sink: Sink, *, store_output: bool) -> Outcome:
        try:
            response = await self._client.post("/api/embed", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return NotSent(type(exc).__name__)
        except httpx.HTTPError as exc:
            return Uncertain(f"transport:{type(exc).__name__}")
        if response.status_code != 200:
            return RuntimeRefused(
                terminal={"status": response.status_code, "error": response.text[:500]},
                reason=f"http_{response.status_code}",
            )
        try:
            document = response.json()
        except ValueError:
            # A 200 whose body is not JSON: the runtime finished something,
            # but what it returned cannot be used. Terminal, and refused.
            return RuntimeRefused(terminal={"status": 200}, reason="malformed_response")
        embeddings = document.get("embeddings")
        terminal = {
            k: document.get(k) for k in ("total_duration", "load_duration", "prompt_eval_count")
        } | {"count": len(embeddings) if isinstance(embeddings, list) else None}
        if not isinstance(embeddings, list):
            return RuntimeRefused(terminal=terminal, reason="no_embeddings")
        sink.emit({"type": "embeddings", "data": embeddings})
        return Completed(
            terminal=terminal,
            result={"embeddings": embeddings} if store_output else None,
        )
