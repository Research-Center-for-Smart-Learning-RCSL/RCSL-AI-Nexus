"""gemma4's tokenizer as the runtime runs it: llama.cpp's BPE (C6b on #24).

These run on small vocabularies built for each rule, so they need no weights.
The real vocabulary is held to the runtime's own token ids in
`test_gemma4_tokenizer_goldens.py`.
"""

from __future__ import annotations

import pytest

from app.adapters.tokenizer.gguf_token_counter.construction import build_tokenizer_for_model
from app.adapters.tokenizer.gguf_token_counter.gemma4_bpe import (
    Gemma4Bpe,
    UnsupportedVocabulary,
)

N, CONTROL, BYTE = 1, 3, 6


def _bpe(tokens: list[str], merges: list[str], types: list[int] | None = None) -> Gemma4Bpe:
    return Gemma4Bpe(tokens, merges, types or [N] * len(tokens))


def _texts(bpe: Gemma4Bpe, tokens: list[str], text: str) -> list[str]:
    return [tokens[i] for i in bpe.encode_ids(text)]


def test_a_token_the_merges_cannot_reach_is_not_used() -> None:
    """The class #25 pinned for Unigram: it picks the best split, so it could
    take `▁abc` in one token where the merges, and the runtime, build two."""
    tokens = ["▁", "a", "b", "c", "▁a", "bc", "▁abc"]
    bpe = _bpe(tokens, ["▁ a", "b c"])

    assert _texts(bpe, tokens, " abc") == ["▁a", "bc"]
    assert len(bpe.encode_ids(" abc" * 20)) == 40, "the deficit would grow with repetition"


def test_merges_apply_lowest_rank_first_then_leftmost() -> None:
    tokens = ["a", "b", "ab", "bb", "abb"]
    by_rank = _bpe(tokens, ["b b", "a b", "a bb"])
    other_order = _bpe(tokens, ["a b", "b b", "ab b"])

    assert _texts(by_rank, tokens, "abb") == ["abb"]  # bb first, then a+bb
    assert _texts(other_order, tokens, "abb") == ["abb"]  # ab first, then ab+b
    assert _texts(_bpe(tokens, ["a b"]), tokens, "abab") == ["ab", "ab"]


def test_spaces_become_the_marker_and_nothing_is_prepended() -> None:
    tokens = ["▁", "a", "▁▁", "▁a"]
    bpe = _bpe(tokens, ["▁ ▁", "▁ a"])

    assert _texts(bpe, tokens, "a  a") == ["a", "▁▁", "a"]  # `▁ ▁` ranks first
    assert _texts(bpe, tokens, " a") == ["▁a"]
    assert _texts(bpe, tokens, "a") == ["a"], "no marker is prepended"


def test_a_run_of_newlines_that_is_a_token_stays_one() -> None:
    tokens = ["\n", "\n\n", "x"]
    bpe = _bpe(tokens, [])

    assert _texts(bpe, tokens, "x\n\nx") == ["x", "\n\n", "x"]
    # Not a token as a whole: falls back to merging, which has no newline pair.
    assert _texts(bpe, tokens, "\n\n\n") == ["\n", "\n", "\n"]


def test_a_missing_symbol_falls_back_to_bytes_and_a_missing_byte_is_dropped() -> None:
    tokens = ["a", "<0xC3>"]
    bpe = _bpe(tokens, [], [N, BYTE])

    assert bpe.encode_ids("aé") == [0, 1], "é is C3 A9 and there is no <0xA9>"


def test_control_tokens_are_split_out_longest_first() -> None:
    tokens = ["<a>", "<a>b", "x", "b"]
    bpe = _bpe(tokens, [], [CONTROL, CONTROL, N, N])

    assert _texts(bpe, tokens, "x<a>bx<a>") == ["x", "<a>b", "x", "<a>"]


def test_end_of_generation_texts_are_special_even_when_typed_normal() -> None:
    tokens = ["<eos>", "x"]
    bpe = _bpe(tokens, [])

    assert _texts(bpe, tokens, "x<eos>") == ["x", "<eos>"]


def test_eos_s_is_ordinary_text_beside_a_tool_response_token() -> None:
    """llama.cpp's "workaround for gemma4": `</s>` leaves the EOG list and
    becomes a normal token, so text spelling it is not one special token."""
    tokens = ["</s>", "<|tool_response>", "<", "/", "s", ">"]
    with_tool = _bpe(tokens, [], [CONTROL, CONTROL, N, N, N, N])
    without = _bpe(["</s>", "<", "/", "s", ">"], [], [CONTROL, N, N, N, N])

    assert len(with_tool.encode_ids("</s>")) == 4
    assert len(without.encode_ids("</s>")) == 1


def test_overlapping_specials_of_one_length_are_refused() -> None:
    with pytest.raises(UnsupportedVocabulary):
        _bpe(["<ab", "ab>"], [], [CONTROL, CONTROL])


def test_a_vocabulary_needing_unported_rules_is_refused() -> None:
    with pytest.raises(UnsupportedVocabulary):
        _bpe(["<|return|>", "x"], [])


def test_sentencepiece_proper_is_not_counted() -> None:
    """Only gemma4 reaches the merges path; any other `llama` vocabulary has
    no runtime-equivalent encoder here and falls back to the estimate."""
    metadata = {
        "tokenizer.ggml.model": "llama",
        "tokenizer.ggml.pre": "default",
        "tokenizer.ggml.tokens": ["a"],
        "tokenizer.ggml.merges": [],
    }
    with pytest.raises(UnsupportedVocabulary):
        build_tokenizer_for_model(metadata)


@pytest.mark.parametrize(("family", "pre"), [("llama", "gemma4"), ("gemma4", None)])
def test_both_spellings_of_a_gemma4_vocabulary_are_counted_as_gemma4(
    family: str, pre: str | None
) -> None:
    metadata: dict[str, object] = {
        "tokenizer.ggml.model": family,
        "tokenizer.ggml.tokens": ["a", "b", "ab"],
        "tokenizer.ggml.merges": ["a b"],
    }
    if pre:
        metadata["tokenizer.ggml.pre"] = pre

    assert build_tokenizer_for_model(metadata).encode("ab").ids == [2]
