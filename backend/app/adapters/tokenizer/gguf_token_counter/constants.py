"""GGUF vocabulary and pre-tokenizer catalog."""

from __future__ import annotations

WANTED_KEYS = (
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.scores",
    "tokenizer.ggml.token_type",
    "tokenizer.ggml.pre",
    "tokenizer.ggml.model",
)


BPE_REQUIRED_KEYS = ("tokenizer.ggml.tokens", "tokenizer.ggml.merges")

UNIGRAM_REQUIRED_KEYS = ("tokenizer.ggml.tokens", "tokenizer.ggml.scores")


CHAT_TEMPLATE_KEY = "tokenizer.chat_template"


BPE_MODEL = "gpt2"

UNIGRAM_MODEL = "llama"

KNOWN_MODELS = frozenset({BPE_MODEL, UNIGRAM_MODEL})


CONTROL_TOKEN_TYPE = 3


PRE_TOKENIZER_PATTERN = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+|\s+(?!\S)|\s+"
)


KNOWN_PRE_TOKENIZERS = frozenset({"qwen2", "qwen35", "gemma4"})
