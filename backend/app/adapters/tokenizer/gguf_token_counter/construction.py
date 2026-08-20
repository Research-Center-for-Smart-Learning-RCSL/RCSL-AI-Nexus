"""Tokenizer vocabulary construction."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.adapters.tokenizer.gguf import iter_merges

from .constants import CONTROL_TOKEN_TYPE, PRE_TOKENIZER_PATTERN


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


def _build_tokenizer(metadata: dict[str, Any]) -> Any:
    from tokenizers import AddedToken, Regex, Tokenizer, decoders, pre_tokenizers
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
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence(
        [
            pre_tokenizers.Split(Regex(PRE_TOKENIZER_PATTERN), behavior="isolated", invert=False),
            # `use_regex=False` because the split above already did that job.
            # Left at its default, ByteLevel applies GPT-2's own pattern on top
            # of this model's, and the two disagree about digits.
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ]
    )
    tokenizer.decoder = decoders.ByteLevel()
    # Control tokens are added as special ones so `<|im_start|>` costs the one
    # token the runtime charges for it rather than the eight its spelling would
    # otherwise be merged into. The template emits them; nothing a caller sends
    # reaches this as a special token, because `add_special_tokens=False` is
    # passed on every encode.
    special = [
        AddedToken(token, special=True, normalized=False)
        for token, kind in zip(tokens, types, strict=False)
        if kind == CONTROL_TOKEN_TYPE
    ]
    if special:
        tokenizer.add_special_tokens(special)
    return tokenizer
