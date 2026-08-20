"""MLX inference request/stream translation."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.hf_validation import assert_valid_hf_repo_id
from app.adapters.runtime.tool_support import should_send_tools
from app.adapters.runtime.transport import timeout_error
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.exceptions import (
    NoAvailableModelError,
    RuntimeCapabilityError,
    StreamInterruptedError,
)

from .base import MlxRuntimeBase
from .translation import _finish_reason, _message_payload, _sampling_payload, _ToolCallAccumulator

logger = logging.getLogger("app.adapters.runtime.mlx_adapter")


class MlxGenerationMixin(MlxRuntimeBase):
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
        """Stream a completion over the OpenAI-compatible endpoint.

        `context_length` is accepted and unused here; see `load` for why MLX
        needs no equivalent of Ollama's `num_ctx`.

        An async generator, declared without `async def` in the port and called
        without await. The `finally` the `async with` provides is what closes the
        upstream request when a client disconnects; without it the server keeps
        generating for someone who has already gone.

        `thinking` is accepted and ignored. `mlx_lm.server` speaks the OpenAI
        chat schema, which has no field for suppressing deliberation, and a
        model that reasons does so inside `content` where this adapter cannot
        separate it. Silently accepting the argument is deliberate: the caller
        asks the port, not the runtime, and a runtime that cannot honour the
        request is not a reason to refuse the generation.

        `tools` are forwarded as the OpenAI `tools` field, which is the schema
        this server already speaks, and calls are read back out of the same
        `delta.tool_calls` fragments an OpenAI client would parse. **This half
        has not been exercised against a live `mlx_lm.server`**, the same
        boundary MLX inference as a whole still sits behind (ROADMAP Phase 2),
        so it is **refused** rather than merely warned about: see
        `_assert_tools_are_verified` for why a warning was not enough and why a
        probe cannot take its place. Ollama is the runtime to point an agent
        capability at until `MLX_TOOL_CALLING_VERIFIED` is earned.
        """
        assert_valid_hf_repo_id(ref)
        payload: dict[str, Any] = {
            "model": ref,
            "messages": [_message_payload(m) for m in messages],
            "stream": True,
            # Ask for a usage total in the terminal frame. If the server does not
            # honour it, the per-chunk counts below still stand.
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            # Stopping at the source beats cutting the stream: the model stops
            # generating rather than producing tokens nobody reads.
            payload["max_tokens"] = max_tokens
        payload.update(_sampling_payload(sampling))
        # Evaluated before the emptiness check, for the reason the Ollama
        # adapter spells out: short-circuiting on `tools` leaves an
        # unenforceable `tool_choice` unrefused when no tools accompany it.
        send_tools = should_send_tools(tool_choice, "mlx_lm.server")
        if tools and send_tools:
            self._assert_tools_are_verified()
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        counted = 0
        finish_reason: str | None = None
        usage_tokens: int | None = None
        usage_prompt_tokens = 0
        saw_terminal = False
        received_any = False
        pending_calls = _ToolCallAccumulator()

        # Converted to a `DomainError` for the reason the Ollama adapter spells
        # out: an httpx exception escapes the router's handler and becomes a 500
        # with no envelope, and "the prompt took longer to evaluate than the
        # read timeout allows" is an ordinary, reachable outcome at a large
        # context rather than a bug.
        try:
            async with (
                httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client,
                client.stream("POST", "/v1/chat/completions", json=payload) as response,
            ):
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    received_any = True
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        saw_terminal = True
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning("mlx emitted a non-JSON SSE line, ignoring")
                        continue

                    if event.get("error"):
                        raise NoAvailableModelError(detail=f"mlx: {event['error']}")

                    choices = event.get("choices") or []
                    if choices:
                        choice = choices[0]
                        delta_body = choice.get("delta") or {}
                        delta = delta_body.get("content") or ""
                        if delta:
                            # Counted one apiece as they arrive, so a disconnect
                            # still bills what was produced. Reconciled against
                            # the server's own total, if it sends one, below.
                            counted += 1
                            yield CompletionChunk(delta=delta, token_count=1)
                        if delta_body.get("tool_calls"):
                            # Accumulated, not yielded. A fragment is a slice of
                            # one call's arguments and is not executable on its
                            # own, so the whole calls go out on the terminal
                            # chunk below. Counted here so a disconnect part way
                            # through a call still bills the tokens it took —
                            # unless this event carried content too and was
                            # already counted above; one event is one decode
                            # step however many fields it fills.
                            #
                            # Deliberately does not set a "saw tool calls" flag:
                            # what the finish reason turns on is whether a call
                            # survives accumulation, which is only knowable at
                            # the drain below.
                            pending_calls.add(delta_body["tool_calls"])
                            if not delta:
                                counted += 1
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                            saw_terminal = True

                    usage = event.get("usage")
                    if usage and usage.get("completion_tokens") is not None:
                        usage_tokens = int(usage["completion_tokens"])
                    if usage and usage.get("prompt_tokens") is not None:
                        # Read as well as `completion_tokens`, which was the
                        # only half the first version took. Leaving it meant
                        # every figure downstream of `CompletionChunk` — the
                        # usage frame, the non-streaming Usage, the quota that
                        # has counted prompt tokens since 2026-08-04 — reported
                        # 0 prompt tokens on this path, and an agent's
                        # consumption is mostly prompt.
                        usage_prompt_tokens = int(usage["prompt_tokens"])
        except httpx.TimeoutException as exc:
            raise timeout_error("mlx", ref, exc, self._timeout, mid_stream=received_any) from exc

        if not saw_terminal:
            # The stream ended without [DONE] or a finish_reason: the server
            # restarted, the model was evicted, or the read timeout fired.
            # Returning quietly would let the caller record a complete generation
            # and report "stop" to the client.
            raise StreamInterruptedError(
                detail=f"mlx stream for {ref} ended without a terminal frame"
            )

        # The authoritative token count arrives only at the end, so emit the
        # difference here. Emitting the whole figure would double-count every
        # token already streamed.
        correction = 0
        if usage_tokens is not None:
            correction = usage_tokens - counted
            if correction < 0:
                logger.info(
                    "mlx completion_tokens=%s below chunk count=%s for %s",
                    usage_tokens,
                    counted,
                    ref,
                )
                correction = 0
        calls = pending_calls.drain()
        yield CompletionChunk(
            delta="",
            tool_calls=calls,
            # From what is actually being forwarded, so the reason and the
            # payload cannot disagree.
            finish_reason=_finish_reason(finish_reason, called_tools=bool(calls)),
            token_count=correction,
            # Reported once, here, for the whole request, like the Ollama
            # adapter's terminal chunk. Zero when the server sent no usage
            # object, which is also what "unknown" has to bill as.
            prompt_tokens=usage_prompt_tokens,
        )

    def _assert_tools_are_verified(self) -> None:
        """Refuse tool calling until somebody has watched this server do it.

        The code below is written and, as of 2026-08-05, has never run against a
        live `mlx_lm.server`. That would ordinarily be a note in a docstring —
        it was one — except that the failure it guards against is invisible: a
        server build without tool support **accepts the `tools` field and
        answers with prose**. The request succeeds, the agent waits for a call
        nobody requested, and every layer in between reports 200. It is the
        exact shape the whole 2026-08-05 tool-calling change exists to remove,
        and leaving it reachable behind a comment meant the platform still
        served it once — to whoever pointed a policy at MLX first.

        **A probe cannot replace this, which is the whole difficulty.** There is
        no capability endpoint to ask, and sending a trial request settles
        nothing: a model that is offered tools and legitimately chooses not to
        call one produces exactly the same response as a server that discarded
        the field. Not-calling is a valid answer, so absence of a call is not
        evidence of anything. That leaves a person, having read a real call off
        the wire, as the only thing that can assert this — which is what the
        setting records.

        So it is a claim about *this deployment's server build*, not about MLX,
        and the honest default is that nobody has checked. Refusing beats
        answering plausibly and wrongly: the same judgement `embed`, `unload`
        and `should_send_tools` already make.
        """
        if self._tool_calling_verified:
            return
        raise RuntimeCapabilityError(
            detail=(
                "tool calling through mlx_lm.server is unverified on this deployment: "
                "a server build without tool support accepts `tools` and answers with "
                "prose, which no client can detect. Route the capability at Ollama, or "
                "set MLX_TOOL_CALLING_VERIFIED=true once a real tool call has been "
                "observed against this server"
            )
        )

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        """Not supported: `mlx_lm.server` serves completions only.

        Refused rather than approximated, which is the same judgement `unload`
        below makes. A plausible-looking vector from the wrong source would not
        fail: it would index the knowledge base with values that retrieve
        confidently and wrongly, and nothing downstream could tell. The routing
        policy for the `embedding` capability should name an Ollama model until
        there is an MLX embedding server to point at.
        """
        assert_valid_hf_repo_id(ref)
        raise RuntimeCapabilityError(
            detail=f"mlx_lm.server has no embeddings endpoint; {ref} cannot embed"
        )
