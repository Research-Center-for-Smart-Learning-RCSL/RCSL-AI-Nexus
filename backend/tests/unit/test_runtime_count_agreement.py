"""The exact counter against counts the runtime actually reported.

Runs only where the measured weights are on disk: set `OLLAMA_MODELS_PATH` to
the model store (the production host's is `/Users/Shared/ollama/models`).
Elsewhere, including CI, every case skips, because without the weights there
is nothing to count with.

What it asserts is the guard's contract (#24): the counter never reports fewer
tokens than the runtime evaluates (`P <= U`), and over-counts by no more than a
small framing margin, so a correct count is not bought by refusing callers.
Both backends must also agree with each other.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from tests.unit.runtime_count_corpus import CORPUS, RECORDED_COUNTS

# The rendered template is the GGUF's Jinja one and the runtime renders its
# own, so a few tokens of framing may differ. Measured at +0 on qwen2.5 and
# +9 to +12 on gemma4 after the 2026-10-08 fixes; this bounds it, it does not
# excuse a content error, which shows up as hundreds.
FRAMING_MARGIN = 16

_ROOT = os.environ.get("OLLAMA_MODELS_PATH")
_CASES = [
    (digest, entry["ref"], name) for digest, entry in RECORDED_COUNTS.items() for name in CORPUS
]


def _vocabularies(ref: str, digest: str):  # type: ignore[no-untyped-def]
    if not _ROOT:
        pytest.skip("OLLAMA_MODELS_PATH is not set")
    root = Path(_ROOT)
    try:
        blob = weights_path(root, ref)
    except (BlobNotFound, OSError):
        pytest.skip(f"{ref} is not in {root}")
    if not blob.name.removeprefix("sha256-").startswith(digest):
        pytest.skip(f"{ref} on disk is not the weights the counts were recorded on")
    counter = GgufTokenCounter(root)
    native = counter._build_native(ref, blob)  # noqa: SLF001 - both backends, by name
    python = counter._build_python(ref, blob)  # noqa: SLF001
    if native is None or python is None:
        pytest.skip(f"no vocabulary for {ref}")
    return native, python


@pytest.mark.parametrize(("digest", "ref", "case"), _CASES)
def test_the_count_bounds_what_the_runtime_evaluates(digest: str, ref: str, case: str) -> None:
    native, python = _vocabularies(ref, digest)
    messages = [{"role": "user", "content": CORPUS[case]}]
    runtime = RECORDED_COUNTS[digest]["counts"][case]  # type: ignore[index]

    native_count = native.count_prompt(messages, [])
    python_count = python.count_prompt(messages, [])

    assert native_count == python_count, (native_count, python_count)
    assert runtime <= native_count <= runtime + FRAMING_MARGIN, (case, native_count, runtime)
