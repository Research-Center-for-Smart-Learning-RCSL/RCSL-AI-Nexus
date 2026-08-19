"""GenerationSession stage."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    SamplingOptions,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import Model
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.exceptions import (
    COUNT_BY_ESTIMATE,
)
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.services.prompt_capture import TranscriptBuffer, should_capture

from .dependencies import RouteChatDependencies
from .finalization import finalize_generation

logger = logging.getLogger("app.application.use_cases.route_chat_request")
_TERMINAL_EVENT_DRAIN_LIMIT = 8


class GenerationSessionMixin(RouteChatDependencies):
    def _resolve_thinking(self, requested: bool | None, policy: RoutingPolicy) -> bool:
        if requested is not None:
            return requested
        if policy.thinking is not None:
            return policy.thinking
        return self._thinking_default

    async def _generate(
        self,
        actor: Actor,
        capability: str,
        target: Model,
        runtime: ModelRuntimePort,
        messages: Sequence[Message],
        max_tokens: int | None,
        thinking: bool,
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        counted_prompt_tokens: int = 0,
        counted_basis: str = COUNT_BY_ESTIMATE,
        requested_capability: str | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        # The caller's request is honoured only where it is stricter than ours.
        # An unbounded generation is a hardware problem, not a client choice.
        ceiling = min(max_tokens or self._max_tokens_ceiling, self._max_tokens_ceiling)

        # Decided once, here, before the first chunk — never per chunk. A
        # window that expires mid-generation must not produce half a
        # transcript: that record is neither the full text somebody asked for
        # nor the absence §9.2 promises by default, and it would read as a
        # truncated answer rather than as an expired window.
        #
        # `None` when the window is shut, which is every ordinary request, and
        # nothing is accumulated at all in that case — not accumulated and
        # discarded. That is the difference between a disclosure control being
        # off and being on with its output thrown away.
        transcript: TranscriptBuffer | None = (
            TranscriptBuffer()
            if self._prompt_logs is not None and should_capture(actor, self._clock.now())
            else None
        )

        produced = 0
        prompt_tokens = 0
        drained = 0
        forwarded_terminal = False
        """Whether a terminal chunk reached the *client*, which is not the same
            as the upstream having sent one: past the ceiling the terminal chunk is
            drained for its token count and deliberately not forwarded. Deciding on
            `upstream_finished` instead would leave a truncated stream with no
            terminal frame at all."""

        completed = False
        truncated = False
        upstream_finished = False
        finish_reason: str | None = None
        """The reason that reached the client, for the transcript. Tracked
            rather than derived at the end because the two terminal paths below
            produce it differently: an upstream `stop` arrives on a chunk, while
            truncation synthesises `length` here."""

        started = self._monotonic()
        """When the request reached the runtime. Recorded as `latency_ms`, which
            is what the caller waited, prompt evaluation included."""

        generating_since: float | None = None
        """When the first chunk arrived, which is when the *deadline* starts.

            Not `started`. The deadline exists to bound a stream that keeps
            producing too slowly to finish, and a runtime evaluating a long prompt
            produces nothing at all while it does so — so measuring from the request
            spent the generation budget before generation began. At a large context
            that is most of the budget: prompt evaluation of a full context has been
            measured on this hardware at over 550 seconds, against a 900 second
            deadline. The stream was then cut on its first token and reported
            `finish_reason: "length"`, telling the client the model had talked too
            much when it had not yet started. What bounds prompt evaluation is the
            per-read timeout, which is the thing that was designed to: no bytes for
            the interval. See infrastructure/config.py, where the two are sized
            together.
            """

        deadline = self._generation_deadline_seconds

        try:
            # `aclosing` on the upstream generator is not optional. When a
            # client disconnects, GeneratorExit is thrown at the `yield` below
            # and this generator's `finally` runs, but the runtime's generator
            # would merely be dropped for the garbage collector to close
            # eventually. Its own `finally` is what closes the upstream HTTP
            # request, so without this the runtime keeps generating tokens for
            # a client that already left. This is the same obligation placed
            # on consumers of this use case.
            async with aclosing(
                runtime.generate(
                    target.ref,
                    messages,
                    ceiling,
                    thinking,
                    tools,
                    tool_choice,
                    sampling,
                    # The same figure `ManageModels.load` gave the runtime, so
                    # this request reuses that runner rather than starting a
                    # second one sized to the model's own maximum.
                    target.resource_profile.context_length,
                )
            ) as upstream:
                async for chunk in upstream:
                    if generating_since is None:
                        generating_since = self._monotonic()
                    # Assigned, not accumulated: the runtime reports it once
                    # for the whole request, on the terminal chunk. Summing
                    # would multiply it by the length of the stream.
                    if chunk.prompt_tokens:
                        prompt_tokens = chunk.prompt_tokens
                    if chunk.finish_reason:
                        upstream_finished = True

                    if truncated:
                        # Past the ceiling: consuming, not forwarding.
                        #
                        # Breaking here instead — which is what this did until
                        # the bug below was found — loses the prompt token
                        # count entirely, because the runtime reports it only
                        # on its terminal event and that event had not been
                        # read yet. `max_tokens: 1` in front of a
                        # context-filling prompt then cost one token of quota:
                        # exactly the hole counting prompt tokens was meant to
                        # close, reopened by the ceiling that runs first.
                        #
                        # Draining is cheap and bounded because the runtime was
                        # told `num_predict = ceiling`, so it stops on the same
                        # token and its terminal event is the very next one.
                        # The bound is a backstop for a runtime that ignores
                        # that, not the expected path.
                        if upstream_finished:
                            # The terminal chunk's own count is a reconciliation
                            # against the runtime's authoritative total, so it
                            # is billed. The content chunks skipped on the way
                            # here are not: they were cut off rather than
                            # delivered, and billing for output withheld from
                            # the caller would be a charge for our own limit.
                            produced += chunk.token_count
                            break
                        drained += 1
                        if drained >= _TERMINAL_EVENT_DRAIN_LIMIT:
                            logger.info(
                                "%s did not send a terminal event within %s chunks of the "
                                "ceiling; prompt tokens go unrecorded for this request",
                                target.ref,
                                _TERMINAL_EVENT_DRAIN_LIMIT,
                            )
                            break
                        continue

                    produced += chunk.token_count
                    if chunk.finish_reason:
                        forwarded_terminal = True
                        finish_reason = chunk.finish_reason
                    # Observed where it is forwarded, so the transcript holds
                    # exactly what the caller was sent. The drained chunks
                    # above are deliberately not observed: they were withheld
                    # at the ceiling, and a record that included them would
                    # disagree with the answer it exists to explain.
                    if transcript is not None:
                        transcript.observe(chunk)
                    yield chunk
                    if produced >= ceiling:
                        truncated = True
                        continue
                    # A wall-clock ceiling as well as a token one. A model
                    # producing slowly enough to stay under the per-read timeout
                    # yet below the token ceiling would otherwise hold a
                    # concurrency slot indefinitely; near swap on unified memory
                    # that is the realistic case. Cutting here reports "length"
                    # through the same block below, the honest signal that the
                    # model did not finish.
                    #
                    # Measured from the first chunk, so that time spent reading
                    # the prompt is not charged against the budget for writing
                    # the answer. See `generating_since`.
                    if deadline > 0 and self._monotonic() - generating_since > deadline:
                        truncated = True
                        logger.info(
                            "generation for %s hit the %ss deadline after %s tokens",
                            target.ref,
                            deadline,
                            produced,
                        )
                        break

            # Only when the upstream did not already send a terminal chunk. At
            # the ceiling the two coincide — Ollama is told `num_predict =
            # ceiling`, so its own done chunk arrives on the same token that
            # trips truncation, and the drain above is what reads it — and
            # emitting a second terminal frame put a chunk after the terminal
            # one on the wire for OpenAI clients. The drained terminal chunk is
            # deliberately not forwarded, so this still fires and the client
            # still sees exactly one terminal frame, reporting `length`.
            if truncated and not forwarded_terminal:
                # Report truncation honestly. Reporting "stop" would tell an
                # OpenAI client the model finished, and those clients decide
                # whether to continue a reply on exactly this field.
                yield CompletionChunk(delta="", finish_reason="length", token_count=0)
                finish_reason = "length"
            completed = not truncated
        finally:
            await finalize_generation(
                usage=self._usage,
                prompt_logs=self._prompt_logs,
                request_id=self._request_id,
                clock=self._clock,
                monotonic=self._monotonic,
                started=started,
                actor=actor,
                capability=capability,
                requested_capability=requested_capability,
                target=target,
                messages=messages,
                produced=produced,
                prompt_tokens=prompt_tokens,
                counted_prompt_tokens=counted_prompt_tokens,
                counted_basis=counted_basis,
                completed=completed,
                transcript=transcript,
                finish_reason=finish_reason,
            )
