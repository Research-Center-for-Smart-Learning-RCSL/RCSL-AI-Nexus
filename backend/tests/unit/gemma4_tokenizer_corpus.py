"""Texts the gemma4 tokenizer port is held to the runtime on (C6b on #24).

Shared by `scripts/runtime-probes/record_tokenizer_goldens.py`, which asks the
runtime for their ids, and `test_gemma4_tokenizer_goldens.py`, which checks
both backends against what it recorded (`gemma4_tokenizer_goldens.py`).
"""

from __future__ import annotations

import random

from app.adapters.runtime.ollama_adapter import message_payload, tool_payload
from app.adapters.tokenizer.gguf_token_counter.gemma4_renderer import (
    Gemma4Renderer,
    renderer_variant,
)
from tests.unit.runtime_validation_corpus import CASES

EDGE_CASES = [
    "",
    " ",
    "a",
    " a",
    "a ",
    "  leading and trailing  ",
    "\n",
    "\n\n",
    "\n" * 40,
    "\r\n\r\n",
    "\t\tindented\n\t\t\tmore",
    " " * 70,
    "x" + " " * 33 + "y",
    "def f(x):\n    return x  # comment\n",
    '{"name": "read_file", "arguments": {"path": "app/main.py"}}',
    "<bos>",
    "<bos><bos>",
    "<eos>",
    "</s>",
    "<s>",
    "<|turn>user\nhi<turn|>\n<|turn>model\n",
    "<|tool_response>",
    "<|tool_response",
    "<|tool",
    "<|<|turn>",
    "<turn|>>",
    "text<eos>text</s>text",
    "繁體中文與日本語のテキスト、한국어도",
    "é é",
    "​‌‍﻿",
    " ▁　",
    "😀🧪👩‍💻🇹🇼",
    "\x00\x01\x07\x1b\x7f",
    "\U0010ffff\U000e0001",
    "𝔘𝔫𝔦𝔠𝔬𝔡𝔢",
    "ﷺ ﷽",
]


def random_texts(seed: int, count: int, specials: list[str]) -> list[str]:
    rng = random.Random(seed)  # noqa: S311 - a reproducible corpus, not a secret
    alphabet = (
        list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        + list(" \t\n\r\n\n   ")
        + list("{}[]()<>|/\\\"'`~!@#$%^&*-_=+;:,.?")
        + list("的一是不了人我在有他這中大來上國個到說們為子和你地出道也時年")
        + list("日本語テキストカタカナ한국어Ελληνικάрусскийعربيעברית")
        + ["😀", "🧪", "👩‍💻", "🇹🇼", "é", "​", " ", "▁", "﻿"]
        + ["\x00", "\x07", "\x1b", "", "\U0001f9ff", "͸", "𝔘"]
    )
    words = [
        "def ", "return ", "function", "import ", "class ", "the ", "and ", "print(",
        "self.", "    ", "\t\t", "\n\n\n", "```python\n", '{"name": ', "</s>", "<s>",
        "<eos>", "<bos>", "<|turn>", "<turn|>", "<|tool_call>", "<tool_call|>", '<|"|>',
        "<|channel>", "<channel|>", "<|think|>", "<|tool_response>", "<|tool", "turn|",
        "<|", "|>",
    ]  # fmt: skip
    out = []
    for _ in range(count):
        parts = []
        for _ in range(rng.choice([1, 2, 5, 20, 80, 300])):
            r = rng.random()
            if r < 0.5:
                parts.append(rng.choice(alphabet))
            elif r < 0.8:
                parts.append(rng.choice(words))
            elif r < 0.9:
                parts.append(rng.choice(specials))
            else:
                parts.append(" " * rng.randint(1, 70))
        out.append("".join(parts))
    return out


def rendered_prompts(ref: str) -> dict[str, str]:
    renderer = Gemma4Renderer(large=renderer_variant(ref) == "large")
    texts = {}
    for name, case in CASES.items():
        if case.only and ref not in case.only:
            continue
        payload = [message_payload(m) for m in case.messages]
        tools = tool_payload(case.tools)
        for think in (None, False):
            texts[f"{name}/think={think}"] = renderer.render(
                messages=payload, tools=tools, think=think
            )
    return texts


def all_texts(seed: int, count: int) -> list[str]:
    """The `texts` the goldens index: the edge cases, then the seeded mix."""
    specials = [s for s in EDGE_CASES if s.startswith("<") and s.endswith(">")]
    return EDGE_CASES + random_texts(seed, count, specials)
