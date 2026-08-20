"""GGUF vocabulary and pre-tokenizer catalog."""

from __future__ import annotations

WANTED_KEYS = (
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.token_type",
    "tokenizer.ggml.pre",
    "tokenizer.ggml.model",
)


REQUIRED_KEYS = ("tokenizer.ggml.tokens", "tokenizer.ggml.merges")


CHAT_TEMPLATE_KEY = "tokenizer.chat_template"


BPE_MODEL = "gpt2"


CONTROL_TOKEN_TYPE = 3


PRE_TOKENIZER_PATTERN = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+|\s+(?!\S)|\s+"
)


KNOWN_PRE_TOKENIZERS = frozenset({"qwen2", "qwen35"})
