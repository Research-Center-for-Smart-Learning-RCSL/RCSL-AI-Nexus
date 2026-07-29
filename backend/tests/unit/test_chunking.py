"""Splitting text into passages.

Pure geometry over strings, so it is tested directly rather than through the
ingestion job. The properties that matter for retrieval quality are that a
passage does not lose a paragraph it could have kept whole, and that a fact
straddling a boundary survives intact in at least one passage.
"""

from __future__ import annotations

import pytest

from app.domain.services.chunking import (
    MAX_CHUNKS_PER_DOCUMENT,
    chunk_text,
)


def test_short_text_is_one_passage() -> None:
    chunks = chunk_text("A single short paragraph.")
    assert [c.text for c in chunks] == ["A single short paragraph."]
    assert chunks[0].index == 0


def test_empty_and_whitespace_only_text_produce_nothing() -> None:
    """A scanned PDF with no text layer parses to this, and it must not become
    a passage of nothing that retrieves against every query."""
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \t ") == []


def test_paragraphs_are_packed_rather_than_cut_at_the_target() -> None:
    """A passage that ends mid-sentence retrieves badly: the embedding of half
    a thought is not close to the embedding of the question it answers."""
    paragraphs = ["A" * 400, "B" * 400, "C" * 400]
    chunks = chunk_text("\n\n".join(paragraphs), chunk_chars=900, overlap_chars=100)

    # 400+400 fits in 900 with the separator; adding the third would not.
    assert len(chunks) == 2
    assert chunks[0].text.count("A") == 400
    assert chunks[0].text.count("B") == 400
    assert chunks[1].text.count("C") == 400
    # No paragraph is split when it did not have to be.
    for chunk in chunks:
        assert "A" * 399 in chunk.text or "B" * 399 in chunk.text or "C" * 399 in chunk.text


def test_a_paragraph_longer_than_the_target_is_hard_split_with_overlap() -> None:
    text = "".join(str(i % 10) for i in range(500))
    chunks = chunk_text(text, chunk_chars=200, overlap_chars=50)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 200
    # Consecutive windows share exactly the overlap, which is what makes a fact
    # spanning a cut appear whole in one of them.
    assert chunks[0].text[-50:] == chunks[1].text[:50]


def test_hard_split_windows_reassemble_the_whole_paragraph() -> None:
    """Overlap must not lose text between windows, only repeat it."""
    text = "".join(str(i % 10) for i in range(1000))
    chunks = chunk_text(text, chunk_chars=300, overlap_chars=60)

    rebuilt = chunks[0].text
    for chunk in chunks[1:]:
        rebuilt += chunk.text[60:]
    assert rebuilt == text


def test_a_trailing_window_that_is_pure_overlap_is_dropped() -> None:
    """A window whose content the previous one already covers in full.

    At 310 characters with a step of 150 the windows start at 0, 150 and 300;
    the third holds ten characters the second already contains, so storing it
    would add a passage that says nothing new. A window that does carry new
    text is kept however short it is, which the length check below pins.
    """
    text = "".join(str(i % 10) for i in range(310))
    chunks = chunk_text(text, chunk_chars=200, overlap_chars=50)

    assert len(chunks) == 2
    # Nothing is lost by the drop: the surviving last window reaches the end.
    assert chunks[-1].text.endswith(text[-10:])


def test_indexes_are_contiguous_from_zero() -> None:
    """Point ids are derived from the index, so a gap would leave a hole that a
    re-index could not overwrite."""
    text = "\n\n".join("p" * 300 for _ in range(10))
    chunks = chunk_text(text, chunk_chars=500, overlap_chars=50)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_the_passage_count_is_bounded() -> None:
    """One upload should not be able to cost an unbounded number of embedding
    calls and stored vectors."""
    text = "".join(str(i % 10) for i in range(2_000_000))
    chunks = chunk_text(text, chunk_chars=100, overlap_chars=10)
    assert len(chunks) == MAX_CHUNKS_PER_DOCUMENT


def test_overlap_must_be_smaller_than_the_chunk() -> None:
    """Otherwise the hard split's step is zero or negative and never advances."""
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("text", chunk_chars=100, overlap_chars=100)


def test_windows_line_endings_do_not_change_the_split() -> None:
    crlf = "one\r\n\r\ntwo"
    lf = "one\n\ntwo"
    assert [c.text for c in chunk_text(crlf)] == [c.text for c in chunk_text(lf)]
