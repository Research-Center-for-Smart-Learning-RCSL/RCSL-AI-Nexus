"""Ollama stream decoding and tool-call accumulation."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.domain.entities.chat import (
    CompletionChunk,
    ToolCall,
)

logger = logging.getLogger("app.adapters.runtime.ollama_adapter")

_FINISH_REASONS = {
    "stop": "stop",
    "length": "length",
    "load": "stop",
    "unload": "stop",
    "tool_calls": "tool_calls",
}


def _finish_reason(done_reason: str | None, *, called_tools: bool) -> str:
    """`tool_calls` wins over whatever Ollama reported.

    Ollama ends a generation that produced tool calls with `done_reason: stop`,
    which is true of the model and wrong for the client: an OpenAI agent loop
    branches on exactly this field to decide whether to execute a call or to
    show the user an answer. Told "stop" it treats the turn as finished and the
    calls are never run, so the conversation stalls with the model waiting on
    results that nobody will produce.

    `called_tools` means "calls are being forwarded", never "the runtime
    mentioned tool calls". The inverse mistake stalls the loop from the other
    end: `tool_calls` with an empty list leaves the client waiting to execute
    something it was never given, and with no content to fall back on.

    **`length` outranks it in turn** (2026-08-09). A generation cut off at the
    token ceiling or the context window may have stopped part way through a
    call's `arguments`, leaving a JSON fragment; reporting `tool_calls` there
    invites the client to execute something incomplete, and reports a truncated
    turn as a finished one on `/v1/responses`, whose `response.incomplete` event
    keys on this value. `stop` is the only reason `tool_calls` needs to
    override, because `stop` is what a *successful* call-producing generation
    reports.
    """
    mapped = _FINISH_REASONS.get(done_reason or "stop", "stop")
    if called_tools:
        return "length" if mapped == "length" else "tool_calls"
    if mapped == "tool_calls":
        logger.warning("ollama reported done_reason=tool_calls with no usable calls")
        return "stop"
    return mapped


def _parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """The id is minted here rather than taken from Ollama, on purpose.

    It is the handle a client uses to pair its tool result back to the call, so
    it has to survive the round trip, which means it must be unique within a
    conversation rather than merely within a chunk — an index would collide
    across turns and pair a result with the wrong call.

    **Whether Ollama supplies one at all is version-dependent**, which is the
    reason not to depend on it. It supplied none when this was written; 0.32.4
    supplies `call_85x6g8ts`-shaped ids (observed 2026-08-05). Neither the
    presence nor the uniqueness of that field is part of any contract Ollama
    publishes, and a runtime that restarted the sequence per turn would produce
    exactly the collision above — silently, as a coherent conversation about the
    wrong thing. Minting unconditionally costs nothing and depends on nothing:
    the id is opaque to the client, which only has to echo back what we sent.
    """
    if not isinstance(raw, list):
        return ()

    calls: list[ToolCall] = []
    for entry in raw:
        function = (entry or {}).get("function") or {}
        name = function.get("name")
        if not name:
            # A call with no name is one no client can execute. Dropped rather
            # than forwarded as an empty call, which would look executable.
            logger.warning("ollama emitted a tool call with no function name, ignoring")
            continue
        arguments = function.get("arguments")
        calls.append(
            ToolCall(
                id=f"call_{uuid.uuid4().hex[:24]}",
                name=name,
                # Back to text, the form the domain holds and the wire carries.
                # `separators` so the bytes match what `sse.py` would produce
                # for the same object, since a client may compare them.
                arguments=(
                    arguments
                    if isinstance(arguments, str)
                    else json.dumps(arguments or {}, separators=(",", ":"))
                ),
            )
        )
    return tuple(calls)


def _spellings(name: str) -> tuple[str, ...]:
    """Every reference Ollama would answer to for a reported model name.

    Ollama canonicalises a bare `nomic-embed-text` to `nomic-embed-text:latest`
    in its own listings, while the registry may hold either spelling. The tag
    lives after the last `/`, so `namespace/name` stays intact."""
    _, _, tail = name.rpartition("/")
    if tail.endswith(":latest"):
        return (name, name[: -len(":latest")])
    return (name,)


class ChatStreamDecoder:
    """Turns Ollama `/api/chat` stream events into `CompletionChunk`s.

    Shared by the adapter, which reads the runtime directly, and the node
    agent's adapter, which reads the same lines relayed by the agent (PR4a on
    #24), so the two cannot decode a stream differently.
    """

    def __init__(self, ref: str) -> None:
        self._ref = ref
        self.counted = 0
        self.saw_done = False
        self.called_tools = False
        self.forwarded_calls: set[tuple[str, str]] = set()
        """(name, arguments) of every call already yielded, consulted only on
        the terminal event. On the build this was written against, calls arrive
        on interim events and the terminal event repeats nothing — but that is
        observed behaviour, not a contract, and a build that restated the
        turn's calls in its done event would have an agent execute every one of
        them twice. Side effects make that the expensive direction to be wrong
        in, so the terminal event is filtered against what was already sent.
        Interim events are never filtered: a model that genuinely asks for the
        same call twice puts both in its own messages, and those go through."""

    def decode(self, event: dict[str, Any]) -> CompletionChunk | None:
        """The chunk for one event, or None for an event that carries nothing.

        After the terminal event `saw_done` is true and the stream is over.
        """
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
            self.saw_done = True
            repeated = tuple(c for c in calls if (c.name, c.arguments) in self.forwarded_calls)
            if repeated:
                logger.warning(
                    "ollama repeated %s already-forwarded tool call(s) "
                    "in its done event for %s, dropping the repeats",
                    len(repeated),
                    self._ref,
                )
                calls = tuple(c for c in calls if c not in repeated)
            if calls:
                self.called_tools = True
            # Ollama reports the authoritative token count only at
            # the end. Chunks were counted as one apiece so that a
            # disconnect still bills something sensible, so emit
            # the difference here rather than the whole figure,
            # which would otherwise be counted twice.
            eval_count = int(event.get("eval_count") or 0)
            correction = eval_count - self.counted
            if correction < 0:
                # Chunks outnumbered the model's own token count.
                # There is no downward correction to make, so this
                # is logged rather than silently over-billed.
                logger.info(
                    "ollama eval_count=%s below chunk count=%s for %s",
                    eval_count,
                    self.counted,
                    self._ref,
                )
                correction = 0
            return CompletionChunk(
                delta=delta,
                reasoning=reasoning,
                tool_calls=calls,
                finish_reason=_finish_reason(
                    event.get("done_reason"), called_tools=self.called_tools
                ),
                token_count=correction,
                # Reported once, here, for the whole request.
                # Ollama has always sent it; nothing read it until
                # 2026-08-04, so every prompt was free of quota.
                prompt_tokens=int(event.get("prompt_eval_count") or 0),
            )

        if delta or reasoning or calls:
            # Reasoning counts. Ollama's `eval_count` includes the
            # thinking tokens, so excluding them here would make the
            # end-of-stream correction re-bill every one of them.
            # Tool calls are decoded tokens too, and a generation
            # that is nothing but a call would otherwise be counted
            # as producing nothing until the terminal correction.
            self.counted += 1
            if calls:
                self.called_tools = True
                self.forwarded_calls.update((c.name, c.arguments) for c in calls)
            return CompletionChunk(
                delta=delta, reasoning=reasoning, tool_calls=calls, token_count=1
            )
        return None
