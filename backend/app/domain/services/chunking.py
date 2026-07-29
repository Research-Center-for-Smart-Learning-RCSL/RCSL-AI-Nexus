"""Splitting a document's text into passages to embed.

Characters, not tokens, for the reason `RouteChatRequest` bounds context in
characters: counting tokens means loading the embedding model's tokeniser into
this process, and a rough bound that is right about the shape of the text is
worth more than an exact one that drags a tokeniser into the domain layer.

The split prefers paragraph boundaries because a passage that ends mid-sentence
retrieves badly: the embedding of half a thought is not close to the embedding
of the question that thought answers. Overlap exists for the same reason, so a
fact that straddles a boundary appears whole in at least one passage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CHUNK_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150

MAX_CHUNKS_PER_DOCUMENT = 5000
"""A bound on how much one upload can cost.

Each chunk is an embedding call and a stored vector, so a document that
produced hundreds of thousands of them would occupy the runtime for a long time
and the index forever. At the default size this is a document of about six
million characters, well past anything the 32 MiB upload ceiling admits as
prose; reaching it means the text is machine-generated, and truncating is the
better failure.
"""

_PARAGRAPH = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    text: str


def chunk_text(
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Split into overlapping passages, largest-boundary-first.

    Paragraphs are accumulated until adding the next would exceed the target,
    which keeps a whole paragraph in one passage wherever one fits. A single
    paragraph longer than the target is hard-split, because there is no smaller
    boundary this is willing to look for: sentence splitting is
    language-specific and gets Chinese, abbreviations and citations wrong in
    ways that are worse than an arbitrary cut.
    """
    if overlap_chars >= chunk_chars:
        raise ValueError("overlap must be smaller than the chunk size")

    normalised = text.replace("\r\n", "\n").strip()
    if not normalised:
        return []

    pieces: list[str] = []
    current = ""
    for paragraph in _PARAGRAPH.split(normalised):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > chunk_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_split(paragraph, chunk_chars, overlap_chars))
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > chunk_chars:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        pieces.append(current)

    trimmed = pieces[:MAX_CHUNKS_PER_DOCUMENT]
    return [Chunk(index=i, text=piece) for i, piece in enumerate(trimmed)]


def _hard_split(paragraph: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    """Fixed-width windows with overlap, for a paragraph with no usable break.

    The step is `chunk_chars - overlap_chars`, so consecutive windows share
    exactly the overlap and a fact spanning a cut survives whole in one of them.
    """
    step = chunk_chars - overlap_chars
    windows = [paragraph[start : start + chunk_chars] for start in range(0, len(paragraph), step)]
    # The final window can be pure overlap when the length lands just past a
    # step boundary, which would store a passage that adds nothing.
    if len(windows) > 1 and len(windows[-1]) <= overlap_chars:
        windows.pop()
    return windows
