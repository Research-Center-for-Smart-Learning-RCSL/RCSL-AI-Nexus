"""Proposal visibility and extraction helpers."""

from __future__ import annotations

from .policy import PROPOSAL_OPEN


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
