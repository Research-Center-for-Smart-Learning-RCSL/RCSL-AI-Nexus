"""Tokenizer vocabulary construction."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from app.adapters.tokenizer.gguf import iter_merges

from .constants import BPE_MODEL, CONTROL_TOKEN_TYPE, PRE_TOKENIZER_PATTERN


class _Vocabulary:
    """One model's tokeniser and chat template, built once and shared.

    Both objects are used from worker threads and neither is mutated after
    construction: `Tokenizer.encode` and `Template.render` each take only a
    shared reference, so no lock is needed around the counting itself. The lock
    in the counter guards *building*, which is a different problem.
    """

    __slots__ = ("_template", "_tokenizer", "blob", "ref")

    def __init__(self, ref: str, blob: str, tokenizer: Any, template: Any) -> None:
        self.ref = ref
        self.blob = blob
        self._tokenizer = tokenizer
        self._template = template

    @property
    def has_template(self) -> bool:
        return self._template is not None

    def encode(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def count_prompt(self, messages: Sequence[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
        rendered = self._template.render(
            messages=list(messages),
            tools=tools or None,
            add_generation_prompt=True,
        )
        return self.encode(rendered)


def _common_pre_tokenizer() -> Any:
    from tokenizers import Regex, pre_tokenizers

    return pre_tokenizers.Sequence(
        [
            pre_tokenizers.Split(Regex(PRE_TOKENIZER_PATTERN), behavior="isolated", invert=False),
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ]
    )


def _add_special_tokens(tokenizer: Any, tokens: list[str], types: list[int]) -> None:
    from tokenizers import AddedToken

    special = [
        AddedToken(token, special=True, normalized=False)
        for token, kind in zip(tokens, types, strict=False)
        if kind == CONTROL_TOKEN_TYPE
    ]
    if special:
        tokenizer.add_special_tokens(special)


def _build_tokenizer(metadata: dict[str, Any]) -> Any:
    from tokenizers import Tokenizer, decoders
    from tokenizers.models import BPE

    tokens: list[str] = metadata["tokenizer.ggml.tokens"]
    merges: list[str] = metadata["tokenizer.ggml.merges"]
    types: list[int] = metadata.get("tokenizer.ggml.token_type") or []
    tokenizer = Tokenizer(
        BPE(
            vocab={token: index for index, token in enumerate(tokens)},
            merges=list(iter_merges(merges)),
            fuse_unk=False,
            byte_fallback=False,
        )
    )
    tokenizer.pre_tokenizer = _common_pre_tokenizer()
    tokenizer.decoder = decoders.ByteLevel()
    _add_special_tokens(tokenizer, tokens, types)
    return tokenizer


def rank_to_log_probability(rank: float) -> float:
    """Turn a GGUF ordinal rank into a log-probability Unigram can segment with.

    GGUF files with ``model: llama`` store a SentencePiece vocabulary whose
    ``scores`` are ordinal ranks — ``gemma4:31b-it-q8_0`` carries exactly
    0.0 to 262143.0 — rather than the log-probabilities SentencePiece itself
    holds. Something has to map one to the other, and **preserving the order is
    not enough**, which is the whole content of this function.

    Unigram segments by maximising the *sum* of log-probabilities over a
    candidate split, so what decides whether "maintenance" stays one token or
    becomes three is the size of the gaps between scores, not their order. The
    mapping here until 2026-09-07 was ``log((N - rank) / N)``, which is
    monotonic and rank-preserving and crushes almost the entire vocabulary
    against zero: rank 1000 lands at -0.0038 and rank 20000 at -0.079. Summing
    several values that close to zero is barely worse than summing one, so the
    segmentation had no reason to prefer whole words and split them.

    Measured that day against the runtime's own ``prompt_eval_count``, on the
    model this matters for, over three texts:

    | text | Ollama | old mapping | this one |
    |---|---:|---:|---:|
    | repetitive prose | 224 | 500 | 220 |
    | ordinary prose | 142 | 355 | 139 |
    | Python source | 303 | 420 | 324 |

    **2.04x over on average, against 1.01x.** The old docstring claimed roughly
    1.4x drift and, worse, claimed the drift under-counted — so a reader
    reasoning about safety from it would have had the direction backwards. It
    over-counted, which never lets a truncating prompt through but does refuse
    callers at a fraction of what the model can read: at a 122880 ceiling the
    incumbent was refusing prompts of about 55,000 real tokens against a model
    that reads 262144.

    ``-log(rank + 1)`` is the Zipfian reading of a rank, and it spreads the
    vocabulary over roughly twelve nats instead of half of one. Scaling or
    offsetting it changes nothing measurable — four variants were tried and
    returned identical counts — so the plainest form is the one kept.
    """
    return -math.log(rank + 1.0)


def _build_unigram_tokenizer(metadata: dict[str, Any]) -> Any:
    """Build a Unigram (SentencePiece) tokenizer from GGUF metadata.

    The scores need converting first; `rank_to_log_probability` is where that
    conversion and its measurement live.
    """
    from tokenizers import Tokenizer, decoders, pre_tokenizers
    from tokenizers.models import Unigram

    tokens: list[str] = metadata["tokenizer.ggml.tokens"]
    scores: list[float] = metadata["tokenizer.ggml.scores"]
    types: list[int] = metadata.get("tokenizer.ggml.token_type") or []

    vocab = [
        (token, rank_to_log_probability(score))
        for token, score in zip(tokens, scores, strict=False)
    ]
    tokenizer = Tokenizer(Unigram(vocab))

    tokenizer.pre_tokenizer = pre_tokenizers.Metaspace(replacement="▁")
    tokenizer.decoder = decoders.Metaspace(replacement="▁")
    _add_special_tokens(tokenizer, tokens, types)
    return tokenizer


def build_tokenizer_for_model(metadata: dict[str, Any]) -> Any:
    family = str(metadata.get("tokenizer.ggml.model", ""))
    if family == BPE_MODEL:
        return _build_tokenizer(metadata)
    return _build_unigram_tokenizer(metadata)
