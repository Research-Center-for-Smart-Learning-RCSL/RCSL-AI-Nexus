"""The SentencePiece path, which had no test and shipped a 2x counting error.

GGUF files with `model: llama` store ordinal ranks where SentencePiece holds
log-probabilities, so something has to convert one to the other. Preserving the
order is not enough and that is the whole difficulty: Unigram segments by
maximising the *sum* of log-probabilities over a candidate split, so whether a
word survives as one token is decided by the size of the gaps between scores.

The mapping until 2026-09-07 was `log((N - rank) / N)` — monotonic, rank
preserving, and crushing almost the whole vocabulary against zero. Summing
several values that close to zero is barely worse than summing one, so the
segmentation had no reason to prefer whole words. Measured against the runtime's
own `prompt_eval_count` it counted 2.04x too many tokens on the model serving
`chat` and `code`, which is a guardrail refusing callers at a fraction of what
the model can read.

Nothing here had a test. These are the two properties that would have caught it:
one on the mapping, and one on what the mapping is for.
"""

from __future__ import annotations

import math

from app.adapters.tokenizer.gguf_token_counter.construction import (
    build_tokenizer_for_model,
    rank_to_log_probability,
)

# A vocabulary shaped like a real one, because the defect does not reproduce in
# a small one. `log((N - rank) / N)` only crushes the scores when N is large:
# over twenty entries every value is near zero and a tie is a tie, so a toy
# vocabulary segments correctly under both mappings and proves nothing.
#
# The pieces sit at better ranks than the whole word, which is the ordinary
# case — `main`, `ten` and `ance` each appear in more words than
# `maintenance` does. A segmenter that can tell a rank of 100 from a rank of
# 2000 still prefers the single token; one that sees both as "about zero"
# takes the three.
# `▁main` and not `main`: Metaspace prepends the marker to the first word, so a
# split that had to spend a separate token on `▁` would lose on token count
# alone and the comparison would never be made. The pieces have to be the ones
# a real segmenter would actually reach for.
_PIECES = {"▁main": 100, "ten": 101, "ance": 102}
_WHOLE = {"▁maintenance": 2000}
_SINGLES = {c: 2500 + i for i, c in enumerate("abcdeghilmnoprstu▁")}
VOCAB_SIZE = 262144


def _metadata() -> dict[str, object]:
    """A GGUF's tokenizer keys, with ranks where SentencePiece has log-probs."""
    entries = {**_PIECES, **_WHOLE, **_SINGLES}
    # Padded to a real vocabulary's size, since that is what the old mapping
    # divided by and what made every gap vanish.
    filler = {f"<pad{i}>": i for i in range(VOCAB_SIZE) if i not in set(entries.values())}
    tokens = dict(sorted({**entries, **filler}.items(), key=lambda kv: kv[1]))
    return {
        "tokenizer.ggml.model": "llama",
        "tokenizer.ggml.tokens": list(tokens),
        "tokenizer.ggml.scores": [float(r) for r in tokens.values()],
        "tokenizer.ggml.token_type": [1] * len(tokens),
    }


def test_the_gaps_between_ranks_survive_the_mapping() -> None:
    """The property the old mapping lost.

    `log((N - rank) / N)` over a 262144-entry vocabulary put rank 1000 at
    -0.0038 and rank 20000 at -0.079: a gap of eight hundredths of a nat across
    nineteen thousand places. Splitting a word into three tokens cost almost
    nothing, so the segmenter split it.
    """
    common = rank_to_log_probability(1_000)
    rarer = rank_to_log_probability(20_000)

    assert common > rarer
    # Nats, and the figure that matters: under the old mapping this was 0.08.
    assert rarer - common < -2.0

    old_common = math.log((VOCAB_SIZE - 1000) / VOCAB_SIZE)
    old_rarer = math.log((VOCAB_SIZE - 20000) / VOCAB_SIZE)
    assert abs(old_rarer - old_common) < 0.1, "the old mapping's gap, for the record"


def test_a_whole_word_in_the_vocabulary_stays_one_token() -> None:
    """What the mapping is for, and what the drift actually was.

    `maintenance` is in this vocabulary and so are the three pieces it would
    break into. A segmenter with no reason to prefer the whole word takes the
    pieces, and every count built on it is too large.
    """
    tokenizer = build_tokenizer_for_model(_metadata())

    encoded = tokenizer.encode("maintenance")

    assert encoded.tokens == ["▁maintenance"], encoded.tokens


def test_the_pieces_are_still_reachable_when_the_whole_is_not() -> None:
    """The fix must not work by ignoring short tokens: a word the vocabulary
    does not hold still has to come apart into ones it does."""
    tokenizer = build_tokenizer_for_model(_metadata())

    encoded = tokenizer.encode("tenance")

    assert encoded.tokens
    assert "".join(encoded.tokens).replace("▁", "") == "tenance"
