"""The exact counter against counts the runtime actually reported.

Runs only where the measured weights are on disk: set `OLLAMA_MODELS_PATH` to
the model store (the production host's is `/Users/Shared/ollama/models`).
Elsewhere, including CI, every case skips, because without the weights there
is nothing to count with.

What it asserts is the guard's contract (#24): the counter never reports fewer
tokens than the runtime evaluates (`P <= U`), and over-counts by no more than a
small framing margin, so a correct count is not bought by refusing callers.
Where the Rust extension is installed, its count must equal the Python one, and
it must really be the Rust encoder: `_build_native` falls back to Python when
the Rust build fails, which would otherwise compare Python with itself.

A pass here is evidence for these weights, this runtime version and this
corpus, not a general bound. Unigram segments by best total score and the
runtime merges adjacent pieces, so the two can differ on some vocabularies
(`test_unigram_vocabulary`); that is why the guard is widened per model only
after this check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter, _NativeVocabulary
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from tests.unit.runtime_count_corpus import CORPUS, RECORDED_COUNTS

# The rendered template is the GGUF's Jinja one and the runtime renders its
# own, so a few tokens of framing may differ. Measured at +0 on qwen2.5 and
# +9 to +12 on gemma4 after the 2026-10-08 fixes. It bounds framing; it does
# not cover a content deficit, which near a context boundary matters at any size.
FRAMING_MARGIN = 16

try:
    import nexus_native  # noqa: F401 - only its presence matters here

    _HAVE_NATIVE = True
except ImportError:
    _HAVE_NATIVE = False

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
    python = counter._build_python(ref, blob)  # noqa: SLF001 - both backends, by name
    assert python is not None, f"no Python vocabulary for {ref}"
    if not _HAVE_NATIVE:
        return None, python
    native = counter._build_native(ref, blob)  # noqa: SLF001
    assert isinstance(native, _NativeVocabulary), (
        f"the Rust encoder did not build for {ref}; got {type(native).__name__}"
    )
    return native, python


@pytest.mark.parametrize(("digest", "ref", "case"), _CASES)
def test_the_count_bounds_what_the_runtime_evaluates(digest: str, ref: str, case: str) -> None:
    native, python = _vocabularies(ref, digest)
    messages = [{"role": "user", "content": CORPUS[case]}]
    runtime = RECORDED_COUNTS[digest]["counts"][case]  # type: ignore[index]

    python_count = python.count_prompt(messages, [])
    assert python_count is not None
    assert runtime <= python_count <= runtime + FRAMING_MARGIN, (case, python_count, runtime)

    if native is not None:
        assert native.count_prompt(messages, []) == python_count
