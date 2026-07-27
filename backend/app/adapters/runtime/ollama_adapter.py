"""Ollama runtime adapter.

Talks to an Ollama running natively on the macOS host, reached through
`host.docker.internal`, because containers on macOS cannot use the GPU. See
docs/ARCHITECTURE.md section 0.1.

Everything goes over the HTTP API. Nothing here builds a shell command, and
every reference passes `parse_model_ref` first.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.validation import assert_valid_model_ref
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import PullProgress
from app.domain.exceptions import DomainError, ModelNotFoundError, NoAvailableModelError

logger = logging.getLogger(__name__)

DEFAULT_KEEP_ALIVE = "10m"

# Ollama's done_reason vocabulary is its own. OpenAI clients branch on
# finish_reason, and an unrecognised value ("load", "unload") reads to them as
# a protocol error, so anything outside the known set is reported as "stop".
_FINISH_REASONS = {"stop": "stop", "length": "length", "load": "stop", "unload": "stop"}


def _finish_reason(done_reason: str | None) -> str:
    return _FINISH_REASONS.get(done_reason or "stop", "stop")


class OllamaAdapter:
    def __init__(
        self, base_url: str, request_timeout_seconds: int = 300, thinking: bool = True
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Only ever sent as `false`. Ollama refuses `think: true` for a model
        # that does not support it — `"qwen2.5:7b" does not support thinking` —
        # so asking for thinking on a mixed registry breaks every non-thinking
        # model, while asking to suppress it is accepted by both kinds. The
        # operator switch is therefore one-directional by necessity, not by
        # preference: leaving it on means sending no `think` field at all and
        # letting each model do what it does.
        self._thinking = thinking
        # Generation legitimately takes minutes, so the read timeout is long,
        # but a host that is simply not there must fail fast rather than
        # holding a concurrency slot for the full request timeout.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(request_timeout_seconds), write=30.0, pool=5.0
        )

    # --- inference -------------------------------------------------------

    def validate_ref(self, ref: str) -> None:
        """Ollama's grammar, exposed so the registry can refuse a reference at
        the moment someone types it rather than at the first download."""
        assert_valid_model_ref(ref)

    async def generate(
        self, ref: str, messages: Sequence[Message], max_tokens: int | None = None
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream a completion.

        An async generator, so it is declared without `async def` in the port
        and called without await. The `finally` inside the `async with` is
        what closes the upstream request when a client disconnects; without
        it Ollama keeps generating for someone who has already gone.
        """
        assert_valid_model_ref(ref)
        payload: dict[str, Any] = {
            "model": ref,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": True,
        }
        if max_tokens is not None:
            # Stopping at the source beats counting chunks and cutting the
            # stream: the model stops generating rather than producing tokens
            # nobody reads.
            payload["options"] = {"num_predict": max_tokens}
        if not self._thinking:
            payload["think"] = False

        counted = 0
        saw_done = False
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("ollama emitted a non-JSON line, ignoring")
                        continue

                    if event.get("error"):
                        raise NoAvailableModelError(detail=f"ollama: {event['error']}")

                    message = event.get("message") or {}
                    delta = message.get("content") or ""
                    # A thinking model puts its deliberation here and leaves
                    # `content` empty until it is finished, which for a hard
                    # question can be the whole generation. Dropping this field
                    # made the adapter produce nothing at all for 93 seconds on
                    # a question that used its entire token budget thinking.
                    reasoning = message.get("thinking") or ""

                    if event.get("done"):
                        saw_done = True
                        # Ollama reports the authoritative token count only at
                        # the end. Chunks were counted as one apiece so that a
                        # disconnect still bills something sensible, so emit
                        # the difference here rather than the whole figure,
                        # which would otherwise be counted twice.
                        eval_count = int(event.get("eval_count") or 0)
                        correction = eval_count - counted
                        if correction < 0:
                            # Chunks outnumbered the model's own token count.
                            # There is no downward correction to make, so this
                            # is logged rather than silently over-billed.
                            logger.info(
                                "ollama eval_count=%s below chunk count=%s for %s",
                                eval_count,
                                counted,
                                ref,
                            )
                            correction = 0
                        yield CompletionChunk(
                            delta=delta,
                            reasoning=reasoning,
                            finish_reason=_finish_reason(event.get("done_reason")),
                            token_count=correction,
                        )
                        return

                    if delta or reasoning:
                        # Reasoning counts. Ollama's `eval_count` includes the
                        # thinking tokens, so excluding them here would make the
                        # end-of-stream correction re-bill every one of them.
                        counted += 1
                        yield CompletionChunk(delta=delta, reasoning=reasoning, token_count=1)

                if not saw_done:
                    # The stream ended without a terminal event: the model was
                    # evicted, Ollama restarted, or the read timeout fired.
                    # Returning quietly would let the caller record a complete
                    # generation and report "stop" to the client.
                    raise NoAvailableModelError(
                        detail=f"ollama stream for {ref} ended without a done event"
                    )

    # --- model lifecycle -------------------------------------------------

    async def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """Stream download progress.

        Also an async generator: Ollama's pull endpoint answers with a stream
        of NDJSON progress objects, so a plain POST would report no progress
        and give no reliable completion signal.
        """
        assert_valid_model_ref(ref)

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream(
                "POST", "/api/pull", json={"model": ref, "stream": True}
            ) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("error"):
                        raise DomainError(detail=f"ollama pull failed: {event['error']}")

                    yield PullProgress(
                        status=event.get("status", ""),
                        completed_bytes=event.get("completed"),
                        total_bytes=event.get("total"),
                    )

    async def load(self, ref: str) -> None:
        """Warm a model into memory.

        An empty prompt with a keep_alive is Ollama's documented way to load
        without generating anything.
        """
        assert_valid_model_ref(ref)
        await self._post("/api/generate", {"model": ref, "keep_alive": DEFAULT_KEEP_ALIVE}, ref)

    async def unload(self, ref: str) -> None:
        """Evict immediately. `keep_alive: 0` is the documented signal."""
        assert_valid_model_ref(ref)
        await self._post("/api/generate", {"model": ref, "keep_alive": 0}, ref)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(5.0)
            ) as client:
                response = await client.get("/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    # --- internals -------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any], ref: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(path, json=payload)
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(detail=f"ollama {path} returned {response.status_code}")

    async def _raise_for_status(self, response: httpx.Response, ref: str) -> None:
        if response.status_code < 400:
            return
        # The body has to be read before it can be inspected on a streamed
        # response, and it goes to the log rather than to the caller: it can
        # name models and paths that a public caller should not learn about.
        await response.aread()
        detail = f"ollama returned {response.status_code} for {ref}: {response.text[:500]}"
        if response.status_code == 404:
            raise ModelNotFoundError(detail=detail)
        raise NoAvailableModelError(detail=detail)
