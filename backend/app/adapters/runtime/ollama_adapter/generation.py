"""Ollama inference request/stream translation."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.tool_support import should_send_tools
from app.adapters.runtime.transport import timeout_error
from app.adapters.runtime.validation import assert_valid_model_ref
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.exceptions import (
    ModelNotFoundError,
    NoAvailableModelError,
    StreamInterruptedError,
)

from .base import OllamaRuntimeBase
from .decoding import _finish_reason, _parse_tool_calls
from .encoding import _sampling_options, _set_num_ctx, message_payload, tool_payload

logger = logging.getLogger("app.adapters.runtime.ollama_adapter")


class OllamaGenerationMixin(OllamaRuntimeBase):
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
        """Stream a completion.

        An async generator, so it is declared without `async def` in the port
        and called without await. The `finally` inside the `async with` is
        what closes the upstream request when a client disconnects; without
        it Ollama keeps generating for someone who has already gone.
        """
        assert_valid_model_ref(ref)
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        if max_tokens is not None:
            # Stopping at the source beats counting chunks and cutting the
            # stream: the model stops generating rather than producing tokens
            # nobody reads.
            options["num_predict"] = max_tokens
        options.update(_sampling_options(sampling))

        payload: dict[str, Any] = {
            "model": ref,
            "messages": [message_payload(m) for m in messages],
            "stream": True,
        }
        if options:
            payload["options"] = options
        # Consulted before the emptiness check, not after it. Short-circuiting
        # on `tools` meant a `tool_choice` the runtime cannot honour went
        # unrefused whenever the caller sent no tools with it, which is 200 and
        # prose where every piece of documentation promises a 400.
        send_tools = should_send_tools(tool_choice, "ollama")
        if tools and send_tools:
            payload["tools"] = tool_payload(tools)
        # Sent on generation as well as on load. Ollama applies its own default
        # to any request that omits it, so a generate without this silently
        # overwrites whatever `load` asked for — which is how a 10-minute
        # setting became a 5-minute one nobody had chosen.
        payload["keep_alive"] = self._keep_alive
        if not thinking:
            # Only ever sent as `false`. Ollama refuses `think: true` for a
            # model that does not support it — `"qwen2.5:7b" does not support
            # thinking` — so a registry holding both kinds cannot ask for
            # thinking at all. `True` here therefore means "send nothing and
            # let the model do what it does", not "ask it to think". That
            # asymmetry is what makes it safe for a caller to send `think: true`
            # over the wire: it never reaches the runtime as a demand.
            #
            # The other direction was checked rather than assumed, because the
            # asymmetry above gives no reason to expect it: `think: false`
            # against `qwen2.5:7b`, which has no thinking capability, returns a
            # normal completion rather than the error `true` earns. So a request
            # that suppresses thinking is safe whichever model routing picks,
            # including the non-thinking fallback.
            #
            # Graded values are not offered because they do not work: Ollama
            # accepts `think: "low"` for this model without error and the
            # behaviour is identical to the default — measured at 8192 tokens,
            # same token count, same 228s, same empty answer.
            payload["think"] = False

        counted = 0
        saw_done = False
        called_tools = False
        forwarded_calls: set[tuple[str, str]] = set()
        """(name, arguments) of every call already yielded, consulted only on
            the terminal event. On the build this was written against, calls arrive
            on interim events and the terminal event repeats nothing — but that is
            observed behaviour, not a contract, and a build that restated the
            turn's calls in its done event would have an agent execute every one of
            them twice. Side effects make that the expensive direction to be wrong
            in, so the terminal event is filtered against what was already sent.
            Interim events are never filtered: a model that genuinely asks for the
            same call twice puts both in its own messages, and those go through."""
        # A timeout here is a `DomainError` or it is a 500. Nothing above this
        # layer handles an httpx exception: it escapes the router's handler,
        # which only knows `DomainError`, so before this the honest and
        # reachable case of "the prompt took longer to evaluate than the read
        # timeout allows" surfaced as an unhandled error with no envelope, or
        # mid-stream as a connection that simply stopped without `[DONE]`.
        #
        # 503 rather than a distinct code. This comment said the caller's
        # remedy is to retry and that a retry usually works off the prefix
        # cache, until 2026-09-02; it is not. A prefill cancelled at the
        # timeout is discarded, measured 2026-08-14, so the remedy is to send
        # less and `transport.py` carries the evidence.
        received_any = False
        try:
            async with (
                httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client,
                client.stream("POST", "/api/chat", json=payload) as response,
            ):
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    received_any = True
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
                    calls = _parse_tool_calls(message.get("tool_calls"))

                    if event.get("done"):
                        saw_done = True
                        repeated = tuple(
                            c for c in calls if (c.name, c.arguments) in forwarded_calls
                        )
                        if repeated:
                            logger.warning(
                                "ollama repeated %s already-forwarded tool call(s) "
                                "in its done event for %s, dropping the repeats",
                                len(repeated),
                                ref,
                            )
                            calls = tuple(c for c in calls if c not in repeated)
                        if calls:
                            called_tools = True
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
                            tool_calls=calls,
                            finish_reason=_finish_reason(
                                event.get("done_reason"), called_tools=called_tools
                            ),
                            token_count=correction,
                            # Reported once, here, for the whole request.
                            # Ollama has always sent it; nothing read it until
                            # 2026-08-04, so every prompt was free of quota.
                            prompt_tokens=int(event.get("prompt_eval_count") or 0),
                        )
                        return

                    if delta or reasoning or calls:
                        # Reasoning counts. Ollama's `eval_count` includes the
                        # thinking tokens, so excluding them here would make the
                        # end-of-stream correction re-bill every one of them.
                        # Tool calls are decoded tokens too, and a generation
                        # that is nothing but a call would otherwise be counted
                        # as producing nothing until the terminal correction.
                        counted += 1
                        if calls:
                            called_tools = True
                            forwarded_calls.update((c.name, c.arguments) for c in calls)
                        yield CompletionChunk(
                            delta=delta, reasoning=reasoning, tool_calls=calls, token_count=1
                        )

                if not saw_done:
                    # The stream ended without a terminal event: the model was
                    # evicted, Ollama restarted, or the read timeout fired.
                    # Returning quietly would let the caller record a complete
                    # generation and report "stop" to the client.
                    raise StreamInterruptedError(
                        detail=f"ollama stream for {ref} ended without a done event"
                    )
        except httpx.TimeoutException as exc:
            raise timeout_error("ollama", ref, exc, self._timeout, mid_stream=received_any) from exc

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for a batch, through Ollama's `/api/embed`.

        The batching endpoint, not the older single-input `/api/embeddings`:
        one round trip per passage would dominate the cost of indexing a
        document. The response's `embeddings` is a list per input, in order.

        **`keep_alive` travels with every batch**, for the reason
        `DEFAULT_KEEP_ALIVE` gives about `generate`: Ollama applies its own
        five-minute default to a request that omits the field, so an embedding
        request would silently overrule whatever `load` asked for. It cost more
        here than it does on the generate path, because routing requires a
        `loaded` observation and nothing on the embedding path loads on demand:
        five minutes after the last search, `embedding` stops resolving to a
        model at all and no traffic can bring it back. Observed 2026-08-18,
        when the runtime moved to its own service account and the embedder was
        the one model that did not return.
        """
        assert_valid_model_ref(ref)
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/api/embed",
                json={"model": ref, "input": list(texts), "keep_alive": self._keep_alive},
            )
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(
                    detail=f"ollama /api/embed returned {response.status_code}"
                )

        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list):
            # A model that is not an embedding model answers 200 with no
            # `embeddings` key. Refusing here is what stops that becoming a
            # knowledge base indexed with nothing.
            raise NoAvailableModelError(detail=f"ollama returned no embeddings for {ref}")
        return [[float(value) for value in vector] for vector in embeddings]
