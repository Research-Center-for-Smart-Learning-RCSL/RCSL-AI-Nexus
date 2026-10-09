"""Both backends against the runtime's own gemma4 token ids (C6b on #24).

The goldens were recorded from the runtime's tokenizer (llama-server's
`/tokenize`), so a pass here is id-for-id equality with what the runtime
evaluates, on the vocabulary it serves: every edge case, the seeded mix, and
whole prompts from the validation corpus as `gemma4_renderer` renders them.
Needs the weights (`OLLAMA_MODELS_PATH`), like the other real-vocabulary tests;
the rules themselves are pinned without them in `test_gemma4_bpe.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf import read_metadata
from app.adapters.tokenizer.gguf_token_counter.gemma4_bpe import Gemma4Bpe
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from tests.unit.gemma4_tokenizer_corpus import all_texts, rendered_prompts
from tests.unit.gemma4_tokenizer_goldens import GOLDENS

try:
    import nexus_native
except ImportError:  # pragma: no cover - the Python backend still runs
    nexus_native = None


@pytest.fixture(scope="module")
def blob() -> Path:
    root = os.environ.get("OLLAMA_MODELS_PATH")
    if not root:
        pytest.skip("OLLAMA_MODELS_PATH is not set")
    try:
        found = weights_path(Path(root), str(GOLDENS["ref"]))
    except (BlobNotFound, OSError):
        pytest.skip(f"{GOLDENS['ref']} is not in {root}")
    if found.name.removeprefix("sha256-") != GOLDENS["weights"]:
        pytest.skip("the weights on disk are not the ones the goldens were recorded on")
    return found


@pytest.fixture(scope="module")
def bpe(blob: Path) -> Gemma4Bpe:
    keys = ("tokenizer.ggml.tokens", "tokenizer.ggml.merges", "tokenizer.ggml.token_type")
    metadata = read_metadata(blob, lambda key: key in keys)
    return Gemma4Bpe(*(metadata[key] for key in keys))


def _record(ids: list[int]) -> tuple[int, str]:
    return len(ids), hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]


def _cases() -> list[tuple[str, str, tuple[int, str]]]:
    texts = all_texts(int(GOLDENS["seed"]), int(GOLDENS["random"]))  # type: ignore[call-overload]
    recorded = GOLDENS["texts"]
    assert isinstance(recorded, list) and len(recorded) == len(texts)
    out = [(f"text-{i}", texts[i], (count, digest)) for i, count, digest in recorded]
    prompts = rendered_prompts(str(GOLDENS["ref"]))
    rendered = GOLDENS["rendered"]
    assert isinstance(rendered, dict) and set(rendered) == set(prompts)
    out += [(name, prompts[name], tuple(rendered[name])) for name in sorted(prompts)]
    return out  # type: ignore[return-value]


CASES = _cases()


@pytest.mark.parametrize(("name", "text", "want"), CASES, ids=[c[0] for c in CASES])
def test_the_python_port_gives_the_runtimes_ids(
    bpe: Gemma4Bpe, name: str, text: str, want: tuple[int, str]
) -> None:
    assert _record(bpe.encode_ids(text)) == want, name


@pytest.mark.skipif(nexus_native is None, reason="the native extension is not built")
def test_the_native_port_gives_the_runtimes_counts(blob: Path) -> None:
    texts = [text for _, text, _ in CASES]
    counts = nexus_native.count_parts(str(blob), "goldens", texts)

    assert counts == [count for _, _, (count, _) in CASES]
