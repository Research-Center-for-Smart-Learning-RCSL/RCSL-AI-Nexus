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

# History, 2026-10-08: on gemma4 the gateway's count minus the runtime's was
# 35 - 4 * rounds (12 / 50 / 100 rounds: -13 / -165 / -365), because gemma4
# ships no chat template and the counter rendered ChatML, with tool calls as
# empty turns. #28 added the omitted calls back (+157 / +575 / +1125). The
# counter now renders gemma4 with a port of the runtime's own renderer (C6c),
# byte-equal to the runtime on this corpus (`render_diff.py`) and pinned in
# `test_gemma4_renderer.py`; these cases now run +2 to +6: the runtime's count
# omits <bos>, and the counter takes the larger of thinking on and off.
# Any deficit found later goes back in this set as a strict xfail.
KNOWN_DEFICITS: set[tuple[str, str]] = set()

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
    for name in entry["cases"]  # type: ignore[attr-defined]
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
    runtime = RECORDED[digest]["cases"][case]["count"]  # type: ignore[index]

    counted = asyncio.run(
        GgufTokenCounter(root).count_prompt(ref, list(shape.messages), list(shape.tools))
    )

    assert counted is not None
    assert runtime <= counted, f"{ref}/{case}: runtime {runtime} > counted {counted}"
