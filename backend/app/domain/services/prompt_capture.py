"""Deciding whether to record a transcript, and accumulating one if so.

Two things live here rather than in `RouteChatRequest`, and for the same
reason in both cases: they are rules about what the platform discloses, and
rules like that belong somewhere a test can reach without a database, an HTTP
request or a runtime.

**The decision is made once, before the first chunk.** `should_capture` is
called at the top of a generation and its answer is fixed for that generation.
Re-checking per chunk would let a window that expires mid-stream produce half a
transcript — a record that is neither the full text somebody asked for nor the
absence of one §9.2 promises by default, and which would read as a truncated
answer rather than as an expired window.

**When the answer is no, nothing is accumulated.** Not accumulated-then-
discarded: `None` is returned and the use case holds no buffer at all, so a
platform running with every window closed — which is every ordinary day —
never has prompt text in process memory on account of this feature. That is
the whole difference between a control that is off and a control that is on
with the output thrown away, and only the first one is worth claiming.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from app.domain.entities.actor import Actor
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.prompt_log import PromptLogEntry

MAX_FIELD_CHARS = 256 * 1024
"""The per-field cap, at roughly a full context window in characters.

The real bound on this table is time — a debug window closes within 24 hours
and the retention sweep removes the rows within days. This is the second bound,
against the single pathological request rather than against accumulation: an
agent client replaying a long tool history into a 64k-token context can produce
a transcript several times the size of anything a person types, and one row
should not be able to cost more than the session it belongs to.

Applied per field so that a very long prompt does not cost the completion,
which is usually the half being read.
"""


def should_capture(actor: Actor, now: datetime) -> bool:
    """Whether this caller's debug window is open right now.

    The window travels on the `Actor` rather than being read from the ambient
    request context, because this is called from the application layer and
    `interfaces/http/request_context` is two layers away. Both identity
    resolvers and the API-key middleware already hold the row it comes from, so
    carrying it costs one field and buys a rule that can be tested with a
    constructed actor and a fixed clock.
    """
    until = actor.debug_logging_until
    return until is not None and now < until


class TranscriptBuffer:
    """Accumulates one generation's output, then builds the row.

    Deltas are collected in a list and joined once at the end rather than
    concatenated per chunk, because a streamed answer arrives as thousands of
    small strings and repeated concatenation makes recording a transcript cost
    quadratic time in the length of the answer — on the same request the
    hardware is already busy with.
    """

    __slots__ = ("_deltas", "_reasoning", "_tool_calls")

    def __init__(self) -> None:
        self._deltas: list[str] = []
        self._reasoning: list[str] = []
        self._tool_calls = 0

    def observe(self, chunk: CompletionChunk) -> None:
        """Called for every chunk the client is sent, and only those.

        Chunks drained past the token ceiling are deliberately not observed:
        they were withheld from the caller, so recording them would make the
        transcript disagree with what the caller actually received — and the
        transcript exists to explain what they received.
        """
        if chunk.delta:
            self._deltas.append(chunk.delta)
        if chunk.reasoning:
            self._reasoning.append(chunk.reasoning)
        self._tool_calls += len(chunk.tool_calls)

    def build(
        self,
        *,
        entry_id: str | None = None,
        at: datetime,
        actor: Actor,
        capability: str,
        model_alias: str,
        request_id: str | None,
        messages: tuple[Message, ...],
        finish_reason: str | None,
        completed: bool,
    ) -> PromptLogEntry:
        rendered = _render_messages(messages)
        completion = "".join(self._deltas)
        reasoning = "".join(self._reasoning)

        truncated: set[str] = set()
        rendered, cut = _cap(rendered)
        if cut:
            truncated.add("messages")
        completion, cut = _cap(completion)
        if cut:
            truncated.add("completion")
        reasoning, cut = _cap(reasoning)
        if cut:
            truncated.add("reasoning")

        return PromptLogEntry(
            id=entry_id or str(uuid.uuid4()),
            at=at,
            actor_id=actor.id,
            api_key_id=actor.api_key_id,
            capability=capability,
            model_alias=model_alias,
            request_id=request_id,
            messages=rendered,
            completion=completion,
            reasoning=reasoning,
            finish_reason=finish_reason,
            completed=completed,
            tool_calls=self._tool_calls,
            tenant_id=actor.tenant_id,
            truncated_fields=frozenset(truncated),
        )


def _cap(value: str) -> tuple[str, bool]:
    """Cut to the limit, and say so — in the return value, not in the text.

    A marker appended to the content would end up read as something the model
    wrote, which is the failure mode of every in-band truncation notice. The
    fact travels beside the data instead, into `truncated_fields`.
    """
    if len(value) <= MAX_FIELD_CHARS:
        return value, False
    return value[:MAX_FIELD_CHARS], True


def _render_messages(messages: tuple[Message, ...]) -> str:
    """The assembled prompt as JSON text.

    Fields are named explicitly rather than dumped from the dataclass, so that
    a field added to `Message` later — for a reason unrelated to this — cannot
    start appearing in stored transcripts because nobody thought about it here.
    Widening what is recorded should be an edit to this function.
    """
    return json.dumps(
        [
            {
                "role": message.role.value,
                "content": message.content,
                **(
                    {
                        "tool_calls": [
                            {
                                "id": call.id,
                                "name": call.name,
                                "arguments": call.arguments,
                            }
                            for call in message.tool_calls
                        ]
                    }
                    if message.tool_calls
                    else {}
                ),
                **({"tool_call_id": message.tool_call_id} if message.tool_call_id else {}),
                **({"name": message.name} if message.name else {}),
            }
            for message in messages
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
