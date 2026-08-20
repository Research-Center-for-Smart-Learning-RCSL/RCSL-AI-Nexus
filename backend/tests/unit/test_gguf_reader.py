from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf import GgufError, iter_merges, read_metadata
from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from tests.unit.exact_token_counting_fixtures import (
    _ARRAY,
    VOCAB,
    _entry,
    _u64,
    write_gguf,
    write_store,
)

pytest_plugins = ("tests.unit.exact_token_counting_fixtures",)


def test_the_reader_keeps_what_was_asked_for_and_walks_past_the_rest(tmp_path: Path) -> None:
    """The saving is the point: the two arrays a vocabulary does not need are
    248320 entries each on the model serving `code`."""
    blob = write_gguf(tmp_path / "blob")

    found = read_metadata(blob, lambda key: key.startswith("tokenizer.ggml."))

    assert found["tokenizer.ggml.model"] == "gpt2"
    assert found["tokenizer.ggml.tokens"] == VOCAB
    assert "test.ignored" not in found
    assert "tokenizer.chat_template" not in found


def test_a_file_that_is_not_a_gguf_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    blob = write_gguf(tmp_path / "blob", magic=b"NOPE")

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_an_unknown_format_version_is_refused(tmp_path: Path) -> None:
    """A version this reader has not been checked on would be parsed by
    guessing at the layout, and the guess would be a vocabulary."""
    blob = write_gguf(tmp_path / "blob", version=99)

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_a_truncated_header_ends_as_an_error_and_not_as_a_short_vocabulary(
    tmp_path: Path,
) -> None:
    blob = write_gguf(tmp_path / "blob")
    blob.write_bytes(blob.read_bytes()[:200])

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_a_value_type_this_reader_has_no_size_for_is_a_gguf_error(tmp_path: Path) -> None:
    """Not a `KeyError`. The two array branches indexed the scalar table before
    checking membership, so a corrupt element type escaped as a bare
    `KeyError` — which `GgufTokenCounter._build` did not catch, which
    `count_prompt` did not catch, and which therefore became a 500 on every
    request routed to that model, re-reading the header each time because a
    build that raises caches nothing."""
    blob = tmp_path / "blob"
    blob.write_bytes(
        b"GGUF"
        + struct.pack("<I", 3)
        + _u64(0)
        + _u64(1)
        + _entry("odd", _ARRAY, struct.pack("<I", 42) + _u64(3) + b"\x00" * 24)
    )

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


async def test_a_blob_that_cannot_be_parsed_falls_back_instead_of_failing(
    tmp_path: Path,
) -> None:
    """The port's contract is that a counter may decline to answer. A file this
    platform does not own is exactly where an unanticipated failure belongs, and
    the cost of letting one through is not a bad count but a refused request."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    (tmp_path / "blobs" / "sha256-abc123").write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\x01" * 9)

    counter = GgufTokenCounter(tmp_path)

    assert await counter.prepare("primary:latest") is False
    assert await counter.count_prompt("primary:latest", [], []) is None


def test_merges_split_on_the_first_space_only() -> None:
    """The commonest merge in a byte-level vocabulary is two spaces, written
    `"Ġ Ġ"`. Splitting on every space turns it into a row the tokeniser then
    does not have."""
    assert list(iter_merges(["Ġ Ġ", "h e"])) == [("Ġ", "Ġ"), ("h", "e")]

    with pytest.raises(GgufError):
        list(iter_merges(["nospace"]))
