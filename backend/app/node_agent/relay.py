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
  timeout, a protocol error, EOF without `done`. These block the node.

A stream is read to its end whatever happens to the caller. The replay buffer
is bounded; past the bound the output is discarded and the attempt is marked
replay-unavailable, and reading continues to `done`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

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
_TERMINAL_FIELDS = (
    "done_reason",
    "eval_count",
    "prompt_eval_count",
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)


def _tag(ref: str) -> str:
    """`/api/tags` names a model with its tag, `latest` included."""
    return ref if ":" in ref.rsplit("/", 1)[-1] else f"{ref}:latest"


class OllamaRelay:
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
        try:
            return (await self._client.get("/api/version")).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(
        self, payload: dict[str, Any], *, store_output: bool, expected_identity: str | None
    ) -> Relay:
        async def run(sink: Sink) -> Outcome:
            mismatch = await self._revision_mismatch(payload["model"], expected_identity)
            if mismatch is not None:
                return mismatch
            return await self._stream_chat(payload, sink, store_output=store_output)

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
        self, payload: dict[str, Any], sink: Sink, *, store_output: bool
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
                async for line in response.aiter_lines():
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
