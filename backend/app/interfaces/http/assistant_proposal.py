"""The text protocol that carries a proposal out of a language model.

A model can only emit text, so a structured suggestion has to travel inside the
answer and be lifted back out. This module owns both halves of that: the
instruction text describing the format (`PROPOSAL_CONTRACT`) and the reader that
parses it (`ProposalCollector`). They live together because they are one
agreement, and splitting them across layers is how the prompt would come to
describe a format the parser no longer accepts — silently, since the failure
mode is a proposal that simply never appears.

`AssistOperator` is handed the contract rather than owning it, which keeps the
dependency pointing the right way: the application layer assembles the rules
that come from the domain, and the interface layer contributes the wire format,
which is its business. `tests/unit/test_assistant_prompt.py` pins that the
assembled prompt contains the marker this module searches for.

**Fail-closed on the proposal, fail-open on the prose.** A malformed, truncated
or out-of-policy proposal yields no proposal frame at all while the written
answer is delivered unchanged. The asymmetry is deliberate: the prose is a
suggestion a person reads, and the proposal is values that land in a form with
one click, so the two do not deserve the same benefit of the doubt.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.schemas.assistant_schemas import ProposalOut

logger = logging.getLogger(__name__)

PROPOSAL_OPEN = "<proposal>"
PROPOSAL_CLOSE = "</proposal>"

PROPOSAL_CONTRACT = f"""\
## How to offer concrete settings

When, and only when, you are recommending specific values the operator could
put into the form in front of them, end your reply with a single block:

{PROPOSAL_OPEN}{{"action":"create","fields":{{...}},"rationale":"..."}}{PROPOSAL_CLOSE}

Rules for that block:

- It must be the last thing in your reply, and there must be at most one.
- `action` is "create" on the create form and "update" on the edit form. On
  "update", also include `key_id` with the id of the key being edited.
- `fields` may contain any of: `name` (string), `scopes` (list of capability
  names), `rate_limit_rpm` (integer, 1 to 100000), `quota_tokens_per_day`
  (integer, 1 or more), `allowed_cidrs` (list of CIDR strings), `expires_at`
  (ISO 8601 timestamp with a UTC offset, e.g. "2026-10-27T00:00:00Z").
- Omit any field you have no recommendation for. Do not guess a value to fill
  the shape; an omitted field leaves what the operator already typed alone.
- `rationale` is one short sentence saying why, in the same language as the
  rest of your reply.
- Never include a key's secret, and never invent one. You cannot see key
  secrets, and the platform shows a key's plaintext exactly once, in the dialog
  that issued it.

The block is not shown to the operator as text. It becomes a card they may
apply to the form with one click, or ignore. Nothing happens automatically, so
explain your recommendation in the prose above it as well.

If you are answering a question rather than recommending values, write only the
answer and no block at all."""


def _visible_prefix(buffer: str) -> str:
    """The part of the accumulated answer that is safe to show *so far*.

    Everything before the opening marker, or — while no marker has been seen —
    everything except a tail that could still turn out to be a partial one. The
    holdback is what stops `<propo` reaching the screen and then being followed
    by a correction nobody can make: the marker arrives split across chunks
    whenever the tokeniser feels like it.
    """
    cut = buffer.find(PROPOSAL_OPEN)
    if cut >= 0:
        return buffer[:cut]
    return buffer[: max(0, len(buffer) - len(PROPOSAL_OPEN) + 1)]


def _final_visible(buffer: str) -> str:
    """The same answer once no more text can arrive, so nothing is held back.

    The holdback exists only to disambiguate a marker still being typed. When
    the generation is over there is nothing left to disambiguate, and a tail
    that is a proper prefix of the marker is a block the model started and did
    not finish — not text, so it is dropped rather than shown.
    """
    cut = buffer.find(PROPOSAL_OPEN)
    if cut >= 0:
        return buffer[:cut]

    for length in range(len(PROPOSAL_OPEN) - 1, 0, -1):
        if buffer.endswith(PROPOSAL_OPEN[:length]):
            return buffer[:-length]
    return buffer


class ProposalCollector:
    """Wraps a generation, hides the proposal block from the visible answer, and
    validates what it finds once the stream is finished.

    One instance per request. `wrap` must be fully consumed before `trailer`
    is read; `sse._frames` guarantees that ordering by calling the trailer only
    after its `async for` has drained the generator.
    """

    def __init__(
        self,
        *,
        now: datetime,
        servable_capabilities: Sequence[str],
        max_lifetime_days: int,
    ) -> None:
        self._now = now
        self._servable = frozenset(servable_capabilities)
        self._max_lifetime = timedelta(days=max_lifetime_days)
        self._buffer = ""
        self._emitted = 0
        self._proposal: ProposalOut | None = None

    async def wrap(
        self, generation: AsyncGenerator[CompletionChunk, None]
    ) -> AsyncGenerator[CompletionChunk, None]:
        # `aclosing` for the same reason every other consumer uses it: this sits
        # between the use case and the framing, and dropping the upstream
        # generator here would leak the concurrency slot exactly as dropping it
        # anywhere else would.
        async with aclosing(generation) as stream:
            async for chunk in stream:
                self._buffer += chunk.delta
                # The holdback is released *on* the terminal chunk rather than
                # after it. Flushing afterwards put a content frame behind the
                # `finish_reason` frame, and a client is right to stop reading
                # there — so every answer silently lost its last nine
                # characters to anything that did not opt into a trailer,
                # including this repository's own reader. The identical mistake
                # is recorded against `RouteChatRequest` in docs/PROGRESS.md,
                # 2026-07-27; it is easy to make twice because the frame that
                # ends a stream is not the last one the code writes.
                visible = (
                    _final_visible(self._buffer)
                    if chunk.finish_reason
                    else _visible_prefix(self._buffer)
                )
                # The chunk is passed through with its delta rewritten rather
                # than dropped when nothing is visible: `finish_reason` and
                # `reasoning` ride on the same chunk, and swallowing one would
                # lose the truncation signal that 2026-07-27 was spent
                # restoring. A chunk with all three empty produces no frames.
                out = visible[self._emitted :]
                self._emitted = len(visible)
                yield replace(chunk, delta=out)

        # Reached when the upstream ended without a terminal chunk at all — a
        # disconnect, or a runtime that simply stops. The branch above has
        # already flushed every stream that ended properly.
        final = _final_visible(self._buffer)
        if len(final) > self._emitted:
            yield CompletionChunk(delta=final[self._emitted :], finish_reason=None, token_count=0)
            self._emitted = len(final)

        self._proposal = self._parse()

    async def trailer(self) -> dict[str, object] | None:
        if self._proposal is None:
            return None
        return {"proposal": self._proposal.model_dump(mode="json", exclude_none=True)}

    # --- parsing ---------------------------------------------------------

    def _parse(self) -> ProposalOut | None:
        raw = self._extract()
        if raw is None:
            return None

        try:
            payload = json.loads(raw)
        except ValueError:
            logger.info("assistant emitted a proposal block that is not JSON")
            return None

        if not isinstance(payload, dict):
            logger.info("assistant proposal was %s, not an object", type(payload).__name__)
            return None

        try:
            proposal = ProposalOut.model_validate(payload)
        except ValidationError as exc:
            # The schema is `UpdateApiKeyRequest`, so this catches every bound
            # the API itself enforces: a zero rate limit, a quota of 0, a name
            # of 200 characters.
            logger.info("assistant proposal failed validation: %s", exc.error_count())
            return None

        return proposal if self._within_policy(proposal) else None

    def _extract(self) -> str | None:
        start = self._buffer.find(PROPOSAL_OPEN)
        if start < 0:
            return None
        end = self._buffer.find(PROPOSAL_CLOSE, start)
        if end < 0:
            # A generation cut short by the token ceiling or the wall-clock
            # deadline lands here. Half a proposal is not a proposal.
            logger.info("assistant proposal block was not terminated")
            return None
        return self._buffer[start + len(PROPOSAL_OPEN) : end]

    def _within_policy(self, proposal: ProposalOut) -> bool:
        """The rules `ManageApiKeys` enforces that the request schema cannot.

        Checked here so the operator is never handed a card that produces an
        error the moment they apply it and submit. This duplicates no rule: the
        bounds come from the same settings value the use case is constructed
        with, and the capability list is the one `ListCapabilities` just
        answered, which is also what fills the form's own picker.
        """
        fields = proposal.fields

        if proposal.action == "update" and not proposal.key_id:
            logger.info("assistant proposed an update naming no key")
            return False

        if fields.scopes is not None:
            unknown = sorted(set(fields.scopes) - self._servable)
            if unknown:
                logger.info("assistant proposed unservable capabilities %s", unknown)
                return False

        if fields.expires_at is not None:
            if fields.expires_at <= self._now:
                logger.info("assistant proposed an expiry in the past")
                return False
            if fields.expires_at > self._now + self._max_lifetime:
                logger.info("assistant proposed an expiry beyond the maximum lifetime")
                return False

        return True
