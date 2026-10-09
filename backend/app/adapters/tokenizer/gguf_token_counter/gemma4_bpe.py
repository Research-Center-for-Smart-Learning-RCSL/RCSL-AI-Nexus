"""gemma4's tokenizer, as the runtime actually runs it (C6b on #24).

The gemma4 GGUFs Ollama publishes say `tokenizer.ggml.model = "llama"`, which
reads as SentencePiece, and this counter used to segment them with HF Unigram.
The runtime does neither. Ollama 0.33.2 serves them through llama.cpp b10630,
and its compatibility layer (`llama/compat/llama-ollama-compat.cpp`,
`handle_gemma4`) rewrites that key to `"gemma4"` before the vocabulary loads,
which selects llama.cpp's **BPE** with the `gemma4` pre-tokenizer. Unigram
picks the best-scoring split and can reach pieces the merges never build, so it
could count fewer tokens than the runtime (20 against 60 on a synthetic
vocabulary, #25); this is the runtime's own algorithm instead, ported from
`src/llama-vocab.cpp` at b10630:

1. **Special tokens are split out first** (`tokenizer_st_partition`, with
   `parse_special`, as llama-server tokenizes a prompt). Which tokens are
   special follows the vocabulary's load: control, user-defined and unknown
   types; tokens on llama.cpp's end-of-generation list are promoted to
   control; and `</s>` is demoted to normal when `<|tool_response>` is also on
   that list (the "workaround for gemma4"). Longer specials are matched first;
   llama.cpp's sort among equal lengths is unstable, so a vocabulary where that
   order could matter is refused rather than guessed at.
2. **Each text fragment** has spaces replaced with `▁`, is split into runs of
   non-newlines and runs of newlines, and a run of newlines that is itself a
   token stays one token (llama.cpp #21343).
3. **Merges** apply to adjacent symbols, starting from single characters, by
   lowest merge rank, leftmost first on a tie.
4. **A symbol that is not a token** falls back to `<0xXX>` per UTF-8 byte; a
   byte with no such token is dropped, as the runtime drops it.

`add_special` is not modelled because the rendered prompt carries `<bos>`
itself: Ollama strips that string and llama-server adds the BOS token back,
one token either way.

Kept in step with `native/src/gemma4_bpe.rs`; both are held to the runtime's
own token ids in `tests/unit/gemma4_tokenizer_goldens.py`.
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Sequence
from dataclasses import dataclass

CONTROL = 3
USER_DEFINED = 4
UNKNOWN = 2

# `llama_vocab::impl::load`: texts promoted to control-type as end-of-generation.
EOG_TEXTS = frozenset(
    {
        "<|eot_id|>",
        "<|im_end|>",
        "<|end|>",
        "<|return|>",
        "<|call|>",
        "<|flush|>",
        "<|calls|>",
        "<end_of_turn>",
        "<|endoftext|>",
        "</s>",
        "<|eom_id|>",
        "<EOT>",
        "_<EOT>",
        "[EOT]",
        "[EOS]",
        "<|end_of_text|>",
        "<end_of_utterance>",
        "<eos>",
        "<turn|>",
        "<|tool_response>",
        "<｜end▁of▁sentence｜>",
        "[e~[",
    }
)
# The gpt-oss hack, which forces these to user-defined.
FORCED_USER_DEFINED = frozenset({"<|channel|>", "<|message|>", "<|start|>", "<|constrain|>"})
# Vocabularies where llama.cpp rewrites attributes by rules this port does not
# carry (the harmony `<|end|>` demotion). None is a gemma4 vocabulary.
UNMODELLED = frozenset({"<|return|>", "<|call|>", "<|calls|>", "<|flush|>"})

_WORDS = re.compile(r"[^\n]+|\n+")


class UnsupportedVocabulary(ValueError):
    """The vocabulary needs a rule this port does not carry; count by estimate."""


@dataclass(frozen=True, slots=True)
class Encoding:
    ids: list[int]


class Gemma4Bpe:
    """Token ids for a gemma4 vocabulary, equal to the runtime's."""

    __slots__ = ("_bytes", "_ids", "_ranks", "_specials")

    def __init__(self, tokens: Sequence[str], merges: Sequence[str], types: Sequence[int]) -> None:
        if UNMODELLED & set(tokens):
            raise UnsupportedVocabulary("the vocabulary carries harmony tokens")
        # `token_to_id[word] = i`: the last duplicate wins.
        self._ids = {token: index for index, token in enumerate(tokens)}
        # `bpe_ranks.emplace`: the first duplicate wins. Split at the first
        # space after position 0, so a pair whose left side is " " survives.
        ranks: dict[tuple[str, str], int] = {}
        for rank, merge in enumerate(merges):
            cut = merge.find(" ", 1)
            pair = (merge[:cut], merge[cut + 1 :]) if cut >= 0 else ("", "")
            ranks.setdefault(pair, rank)
        self._ranks = ranks
        self._bytes = [self._ids.get(f"<0x{b:02X}>") for b in range(256)]
        self._specials = _special_tokens(tokens, types)

    def encode(self, text: str, add_special_tokens: bool = False) -> Encoding:
        if add_special_tokens:
            raise ValueError("the rendered prompt carries its own <bos>")
        return Encoding(self.encode_ids(text))

    def encode_ids(self, text: str) -> list[int]:
        out: list[int] = []
        for fragment, special in self._partition(text):
            if special is not None:
                out.append(special)
            else:
                self._tokenize(fragment.replace(" ", "▁"), out)
        return out

    def _partition(self, text: str) -> list[tuple[str, int | None]]:
        fragments: list[tuple[str, int | None]] = [(text, None)] if text else []
        for special in self._specials:
            token_id = self._ids[special]
            split: list[tuple[str, int | None]] = []
            for value, known in fragments:
                if known is not None or special not in value:
                    split.append((value, known))
                    continue
                pieces = value.split(special)
                for i, piece in enumerate(pieces):
                    if i:
                        split.append((special, token_id))
                    if piece:
                        split.append((piece, None))
            fragments = split
        return fragments

    def _tokenize(self, text: str, out: list[int]) -> None:
        for word in _WORDS.findall(text):
            if word[0] == "\n" and word in self._ids:
                out.append(self._ids[word])
                continue
            for symbol in self._merge(word):
                token = self._ids.get(symbol)
                if token is not None:
                    out.append(token)
                    continue
                out.extend(b for b in (self._bytes[c] for c in symbol.encode()) if b is not None)

    def _merge(self, word: str) -> list[str]:
        symbols: list[str] = list(word)
        nxt = list(range(1, len(symbols) + 1))
        nxt[-1] = -1
        prv = list(range(-1, len(symbols) - 1))
        queue: list[tuple[int, int, int, str]] = []
        ranks = self._ranks

        def push(left: int, right: int) -> None:
            if left < 0 or right < 0:
                return
            rank = ranks.get((symbols[left], symbols[right]))
            if rank is not None:
                heapq.heappush(queue, (rank, left, right, symbols[left] + symbols[right]))

        for i in range(1, len(symbols)):
            push(i - 1, i)
        while queue:
            _, left, right, text = heapq.heappop(queue)
            if not symbols[left] or not symbols[right] or symbols[left] + symbols[right] != text:
                continue
            symbols[left] = text
            symbols[right] = ""
            nxt[left] = nxt[right]
            if nxt[right] >= 0:
                prv[nxt[right]] = left
            push(prv[left], left)
            push(left, nxt[left])
        return [s for s in symbols if s]


def _special_tokens(tokens: Sequence[str], types: Sequence[int]) -> list[str]:
    """The tokens `tokenizer_st_partition` splits out, longest first."""
    attrs = {i: (types[i] if i < len(types) else 1) for i in range(len(tokens))}
    present = {token: i for i, token in enumerate(tokens)}
    for text in EOG_TEXTS & present.keys():
        if attrs[present[text]] != CONTROL:
            attrs[present[text]] = CONTROL
    for text in FORCED_USER_DEFINED & present.keys():
        attrs[present[text]] = USER_DEFINED
    if "<|tool_response>" in present and "</s>" in present:
        attrs[present["</s>"]] = 1
    special = [tokens[i] for i, kind in attrs.items() if kind in (CONTROL, USER_DEFINED, UNKNOWN)]
    by_length: dict[int, list[str]] = {}
    for token in special:
        by_length.setdefault(len(token.encode()), []).append(token)
    for same in by_length.values():
        if _order_matters(same):
            raise UnsupportedVocabulary(
                f"equal-length special tokens can overlap, so llama.cpp's unstable sort "
                f"decides between them: {sorted(same)[:4]}"
            )
    return [token for length in sorted(by_length, reverse=True) for token in by_length[length]]


def _order_matters(same_length: list[str]) -> bool:
    """Whether two equal-length specials can overlap in some text.

    Two different strings of one length can only compete for the same bytes
    when a proper suffix of one is a prefix of the other.
    """
    if len(same_length) < 2:
        return False
    prefixes: set[str] = set()
    for token in same_length:
        prefixes.update(token[:k] for k in range(1, len(token)))
    for token in same_length:
        if any(token[k:] in prefixes for k in range(1, len(token))):
            return True
    return False
