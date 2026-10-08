"""Ollama inference request/stream translation."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence

import httpx

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
from .decoding import ChatStreamDecoder
from .encoding import chat_payload, embed_payload

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
        payload = chat_payload(
            ref,
            messages,
            max_tokens=max_tokens,
            thinking=thinking,
            tools=tools,
            tool_choice=tool_choice,
            sampling=sampling,
            context_length=context_length,
            keep_alive=self._keep_alive,
        )

        decoder = ChatStreamDecoder(ref)
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

                    chunk = decoder.decode(event)
                    if chunk is not None:
                        yield chunk
                    if decoder.saw_done:
                        return

                if not decoder.saw_done:
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
                json=embed_payload(ref, texts, keep_alive=self._keep_alive),
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
