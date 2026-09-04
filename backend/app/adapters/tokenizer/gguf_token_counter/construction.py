"""Tokenizer vocabulary construction."""

from __future__ import annotations

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


def _build_unigram_tokenizer(metadata: dict[str, Any]) -> Any:
    """Build a Unigram (SentencePiece) tokenizer from GGUF metadata.

    GGUF files with ``model: llama`` store a SentencePiece vocabulary where the
    ``scores`` field carries ordinal ranks rather than true log-probabilities.
    The mapping ``log((N - rank) / N)`` produces a monotonically decreasing
    log-probability that preserves the rank order, which is what the Unigram
    model needs to prefer common tokens over rare ones.

    The resulting tokenization does not match the runtime's native tokenizer
    exactly — measured drift is roughly 1.4x on ``gemma4:31b-it-q8_0`` — but
    it is substantially closer than the character estimate (which drifts to
    0.34x on dense ASCII). The drift is in the safe direction: this
    under-counts, so a prompt reported as over the ceiling is genuinely over.
    """
    import math

    from tokenizers import Tokenizer, decoders, pre_tokenizers
    from tokenizers.models import Unigram

    tokens: list[str] = metadata["tokenizer.ggml.tokens"]
    scores: list[float] = metadata["tokenizer.ggml.scores"]
    types: list[int] = metadata.get("tokenizer.ggml.token_type") or []
    n = len(tokens)

    vocab = [
        (token, math.log((n - score) / n) if n - score > 0 else -100.0)
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
