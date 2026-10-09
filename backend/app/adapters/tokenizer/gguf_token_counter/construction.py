"""Tokenizer vocabulary construction."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.adapters.tokenizer.gguf import iter_merges

from . import fingerprint
from .constants import (
    BPE_MODEL,
    GEMMA4_MODEL,
    PRE_TOKENIZER_PATTERN,
    SENTENCEPIECE_MODEL,
)
from .gemma4_bpe import Gemma4Bpe, UnsupportedVocabulary, special_tokens


class _Vocabulary:
    """One model's tokeniser and chat template, built once and shared.

    Both objects are used from worker threads and neither is mutated after
    construction: `Tokenizer.encode` and `Template.render` each take only a
    shared reference, so no lock is needed around the counting itself. The lock
    in the counter guards *building*, which is a different problem.
    """

    __slots__ = ("_template", "_tokenizer", "blob", "ref", "renderer")

    def __init__(
        self, ref: str, blob: str, tokenizer: Any, template: Any, renderer: str | None = None
    ) -> None:
        self.ref = ref
        self.blob = blob
        self._tokenizer = tokenizer
        self._template = template
        self.renderer = renderer
        """Which rendering code this is (`fingerprint`); None for a fallback."""

    @property
    def encoder(self) -> str:
        return fingerprint.python_encoder()

    @property
    def has_template(self) -> bool:
        return self._template is not None

    @property
    def template(self) -> Any:
        return self._template

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
    """The tokens llama.cpp splits out before encoding, as single tokens.

    Not only control-type: llama.cpp also splits user-defined tokens (qwen2.5's
    `<tool_call>`) and promotes its end-of-generation texts (`</s>`, ...), and
    counting those as text made qwen count high on half of a random corpus
    (measured against the runtime's own ids, PR2b on #24). The same rules as
    the gemma4 port, `gemma4_bpe.special_tokens`.
    """
    from tokenizers import AddedToken

    special = [
        AddedToken(token, special=True, normalized=False) for token in special_tokens(tokens, types)
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


def build_tokenizer_for_model(metadata: dict[str, Any]) -> Any:
    family = str(metadata.get("tokenizer.ggml.model", ""))
    scheme = str(metadata.get("tokenizer.ggml.pre", "gemma4" if family == GEMMA4_MODEL else ""))
    if family == BPE_MODEL:
        return _build_tokenizer(metadata)
    if family == GEMMA4_MODEL or (family == SENTENCEPIECE_MODEL and scheme == "gemma4"):
        return Gemma4Bpe(
            metadata["tokenizer.ggml.tokens"],
            metadata["tokenizer.ggml.merges"],
            metadata.get("tokenizer.ggml.token_type") or [],
        )
    # SentencePiece proper is not counted: Unigram can under-count it (#25),
    # and no model here is served by it to port from (C6b).
    raise UnsupportedVocabulary(
        f"tokenizer model {family!r} with pre-tokeniser {scheme!r} has no "
        "runtime-equivalent encoder"
    )
