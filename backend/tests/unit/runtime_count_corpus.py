"""Texts whose runtime token counts are recorded, for checking the exact counter.

The counter's whole claim is that it agrees with `prompt_eval_count`, and only
the runtime can answer that. So the runtime's answers are measured once, by
`scripts/runtime-probes/record_prompt_counts.py`, and kept in
`RECORDED_COUNTS` beside the texts they were measured on;
`test_runtime_count_agreement.py` checks the counter against them wherever the
same weights are on disk.

The corpus spans what a whitespace-only check would miss (#24): word
boundaries, punctuation, CJK with and without spaces, tabs, blank lines,
indentation, JSON, identifiers, and text that looks like a control token.
Changing a text invalidates its recorded counts; re-record rather than edit.
"""

from __future__ import annotations

import json

_CODE = '''class RoutingService:
    """Pick a model for a capability."""

    def select(self, policy, models, nodes):
        for candidate in sorted(policy.candidates, key=lambda c: -c.priority):
            model = models.get(candidate.model_alias)
            if model is None:
                continue
            if self._satisfies(candidate.require, model, nodes):
                return model
        raise NoAvailableModelError(detail=f"capability={policy.capability}")
'''

CORPUS: dict[str, str] = {
    "x": "x",
    "spaces_64": "a" + " " * 64 + "b",
    "spaces_mixed": "a b  c   d    e     f",
    "tabs": "def f():\n\tif x:\n\t\treturn 1\n",
    "newlines": "a\n\n\nb\n \n  \nc",
    "indent_block": "def f():\n" + "        x = 1\n" * 50,
    "source_code": _CODE * 4,
    "prose_en": "The quick brown fox jumps over the lazy dog. It's a well-known pangram, isn't it?",
    "punct": "Hello, world! (a) [b] {c} -- x=1; y:=2... \"quoted\" 'single' a/b\\c @#$%^&*",
    "cjk": (
        "本平台將 Mac Studio 視為全天候運作的 AI 伺服器。日本語のテキストも、한국어 텍스트도 있다。"
    ),
    "cjk_spaced": "你 好 世 界 ， 這 是 測 試",
    "mixed_code_cjk": "# 計算總和\nfor i in range(10):  # 迴圈\n    total += i  # 累加",
    "json": json.dumps({"a": [1, 2, {"b": "c d"}], "e": None}, indent=2),
    "uuids": " ".join(["3f2b8c1e-9a4d-4e7b-8c2f-1a2b3c4d5e6f"] * 20),
    "leading_space": "   leading and trailing   ",
    "special_like": "<start_of_turn> not a real turn <end_of_turn>",
}

# `prompt_eval_count` for `[{"role": "user", "content": text}]` with
# `think: false`, keyed by the first 12 hex digits of the weights blob. The
# whole prompt, framing included, because that is what the guard compares.
# `manifest` is the served manifest the recorder verified against the store.
# Recorded 2026-10-08 on the production host.
RECORDED_COUNTS: dict[str, dict[str, object]] = {
    "a0feadb736f5": {
        "ref": "gemma4:31b-it-q8_0",
        "manifest": "53dd8459790f",
        "ollama": "0.33.2",
        "counts": {
            "x": 14,
            "spaces_64": 18,
            "spaces_mixed": 23,
            "tabs": 26,
            "newlines": 22,
            "indent_block": 316,
            "source_code": 456,
            "prose_en": 38,
            "punct": 50,
            "cjk": 46,
            "cjk_spaced": 24,
            "mixed_code_cjk": 41,
            "json": 54,
            "uuids": 752,
            "leading_space": 16,
            "special_like": 31,
        },
    },
    "2bada8a74506": {
        "ref": "qwen2.5:7b",
        "manifest": "845dbda0ea48",
        "ollama": "0.33.2",
        "counts": {
            "x": 30,
            "spaces_64": 32,
            "spaces_mixed": 39,
            "tabs": 40,
            "newlines": 35,
            "indent_block": 332,
            "source_code": 393,
            "prose_en": 51,
            "punct": 66,
            "cjk": 65,
            "cjk_spaced": 46,
            "mixed_code_cjk": 61,
            "json": 64,
            "uuids": 768,
            "leading_space": 34,
            "special_like": 43,
        },
    },
}
