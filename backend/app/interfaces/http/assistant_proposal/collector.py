"""Streaming proposal collector, parser, and policy coordinator."""

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

from .extraction import _final_visible, _visible_prefix
from .policy import PROPOSAL_CLOSE, PROPOSAL_OPEN
from .validation import ProposalPolicyMixin

logger = logging.getLogger("app.interfaces.http.assistant_proposal")


class ProposalCollector(ProposalPolicyMixin):
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
        dumped = self._proposal.model_dump(mode="json", exclude_none=True)

        # `exclude_none` is right for every field but one. On this model `None`
        # means "the assistant made no recommendation", and dropping those is
        # what keeps a card from claiming edits it did not propose — except on
        # `default_capability`, where `None` is the recommendation: it is the
        # setting that says stop substituting. Excluded, the one card that can
        # withdraw a default would arrive with the field missing, and applying
        # it would leave the default in place while the card said otherwise.
        #
        # The same distinction `PATCH /admin/api-keys/{key_id}` draws with
        # `model_fields_set`, at the other end of the same field. Both exist
        # because absence and null are different answers here and nowhere else.
        fields = self._proposal.fields
        dumped_fields = dumped.get("fields")
        if "default_capability" in fields.model_fields_set and isinstance(dumped_fields, dict):
            dumped_fields["default_capability"] = fields.default_capability

        return {"proposal": dumped}

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
