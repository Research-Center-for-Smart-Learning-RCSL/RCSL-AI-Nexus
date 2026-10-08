"""Profile validation: does the guard's count bound what the runtime evaluates?

The contract (#24 final spec §6) is `P <= U`: the runtime's count of the whole
prompt never exceeds the gateway's. This checks it on the shapes the gateway
sends (tools, tool loops, thinking, repetition, near-boundary), through the
counter the guard actually calls, against counts the runtime reported. Like the
encoder agreement test it runs only where the recorded weights are on disk.

A case that fails is a profile that may **not** be validated: the guard keeps
the legacy `num_ctx // 2` rule for it. Known failures are marked `xfail`
(strict), so they stay visible and a fix announces itself.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from tests.unit.runtime_validation_corpus import CASES, RECORDED

_ROOT = os.environ.get("OLLAMA_MODELS_PATH")

# Measured 2026-10-08: gemma4 renders each tool round ~3 tokens longer at the
# runtime than through the GGUF template, so a long tool loop is under-counted
# (12 rounds: runtime 2800, gateway 2787). Encoder agreement holds on the same
# weights, so this is the renderer, not the tokenizer. Until the counter
# renders tool turns as the runtime does, gemma4's tool profile is not valid.
KNOWN_DEFICITS = {("gemma4:31b-it-q8_0", "tool_loop_12")}

_CASES = [
    pytest.param(
        digest,
        entry["ref"],
        name,
        marks=pytest.mark.xfail(strict=True, reason="known renderer deficit")
        if (entry["ref"], name) in KNOWN_DEFICITS
        else (),
        id=f"{entry['ref']}-{name}",
    )
    for digest, entry in RECORDED.items()
    for name in entry["counts"]  # type: ignore[attr-defined]
]


@pytest.mark.parametrize(("digest", "ref", "case"), _CASES)
def test_the_guard_count_bounds_the_runtime_count(digest: str, ref: str, case: str) -> None:
    if not _ROOT:
        pytest.skip("OLLAMA_MODELS_PATH is not set")
    root = Path(_ROOT)
    try:
        blob = weights_path(root, ref)
    except (BlobNotFound, OSError):
        pytest.skip(f"{ref} is not in {root}")
    if not blob.name.removeprefix("sha256-").startswith(digest):
        pytest.skip(f"{ref} on disk is not the weights the counts were recorded on")
    shape = CASES[case]
    runtime = RECORDED[digest]["counts"][case]  # type: ignore[index]

    counted = asyncio.run(
        GgufTokenCounter(root).count_prompt(ref, list(shape.messages), list(shape.tools))
    )

    assert counted is not None
    assert runtime <= counted, f"{ref}/{case}: runtime {runtime} > counted {counted}"
