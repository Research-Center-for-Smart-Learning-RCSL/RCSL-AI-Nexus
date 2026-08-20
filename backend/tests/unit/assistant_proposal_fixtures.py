"""The text protocol that carries a proposal out of a model.

Two halves are worth pinning and neither is obvious from reading the code.

The **stripping** half: a proposal block travels inside the answer, so the
reader has to hide it without hiding the answer, while the marker arrives split
across chunks at whatever boundary the tokeniser chose. Getting that wrong puts
`<propo` on the screen, or swallows the last words of every reply.

The **validating** half: what survives lands in a form with one click, so
anything malformed, truncated or outside what the platform would accept must
produce no card at all. The prose is delivered either way — the operator asked
a question and deserves the answer even when the machine-readable part of it
was unusable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.assistant_proposal import (
    PROPOSAL_CLOSE,
    PROPOSAL_OPEN,
    ProposalCollector,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

SERVABLE = ["chat", "code"]


def collector(max_lifetime_days: int = 365) -> ProposalCollector:
    return ProposalCollector(
        now=NOW,
        servable_capabilities=SERVABLE,
        max_lifetime_days=max_lifetime_days,
    )


async def drain(c: ProposalCollector, pieces: list[str]) -> str:
    """Feed the collector one chunk per piece and return what stayed visible."""

    async def generation() -> AsyncIterator[CompletionChunk]:
        for piece in pieces:
            yield CompletionChunk(delta=piece)

    seen = []
    async for chunk in c.wrap(generation()):
        seen.append(chunk.delta)
    return "".join(seen)


def block(payload: dict) -> str:
    return PROPOSAL_OPEN + json.dumps(payload) + PROPOSAL_CLOSE


def valid_payload(**overrides: object) -> dict:
    payload: dict = {
        "action": "create",
        "fields": {"scopes": ["chat"], "rate_limit_rpm": 60},
        "rationale": "A narrow key for one integration.",
    }
    payload.update(overrides)
    return payload
