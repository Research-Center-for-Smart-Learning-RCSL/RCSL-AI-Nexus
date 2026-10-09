"""Both backends against the runtime's own token ids (C6b and PR2b on #24).

The goldens were recorded from each model's runner (llama-server's
`/tokenize`), so a pass here is id-for-id equality with what the runtime
evaluates, on the vocabulary it serves: every edge case, the seeded mix, and
for gemma4 whole prompts from the validation corpus as `gemma4_renderer`
renders them. qwen2.5 joined when its encoder took llama.cpp's special-token
rules; it was counting high on half of the mix before (PR2b). Needs the
weights (`OLLAMA_MODELS_PATH`); the rules themselves are pinned without them in
`test_gemma4_bpe.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.adapters.tokenizer.gguf import read_metadata
from app.adapters.tokenizer.gguf_token_counter.constants import WANTED_KEYS
from app.adapters.tokenizer.gguf_token_counter.construction import build_tokenizer_for_model
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from tests.unit import gemma4_tokenizer_goldens, qwen_tokenizer_goldens
from tests.unit.gemma4_tokenizer_corpus import all_texts, rendered_prompts

try:
    import nexus_native
except ImportError:  # pragma: no cover - the Python backend still runs
    nexus_native = None

SETS: dict[str, dict[str, Any]] = {
    "gemma4": gemma4_tokenizer_goldens.GOLDENS,
    "qwen": qwen_tokenizer_goldens.GOLDENS,
}


def _blob(goldens: dict[str, Any]) -> Path:
    root = os.environ.get("OLLAMA_MODELS_PATH")
    if not root:
        pytest.skip("OLLAMA_MODELS_PATH is not set")
    try:
        found = weights_path(Path(root), str(goldens["ref"]))
    except (BlobNotFound, OSError):
        pytest.skip(f"{goldens['ref']} is not in {root}")
    if found.name.removeprefix("sha256-") != goldens["weights"]:
        pytest.skip("the weights on disk are not the ones the goldens were recorded on")
    return found


def _record(ids: list[int]) -> tuple[int, str]:
    return len(ids), hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]


def _cases(goldens: dict[str, Any]) -> list[tuple[str, str, tuple[int, str]]]:
    texts = all_texts(int(goldens["seed"]), int(goldens["random"]))
    recorded = goldens["texts"]
    assert len(recorded) == len(texts)
    out = [(f"text-{i}", texts[i], (count, digest)) for i, count, digest in recorded]
    if goldens["rendered"]:
        prompts = rendered_prompts(str(goldens["ref"]))
        assert set(goldens["rendered"]) == set(prompts)
        out += [(n, prompts[n], tuple(goldens["rendered"][n])) for n in sorted(prompts)]
    return out  # type: ignore[return-value]


@pytest.mark.parametrize("model", sorted(SETS))
def test_the_python_encoder_gives_the_runtimes_ids(model: str) -> None:
    goldens = SETS[model]
    blob = _blob(goldens)
    metadata = read_metadata(blob, lambda key: key in WANTED_KEYS)
    encoder = build_tokenizer_for_model(metadata)

    wrong = [
        name
        for name, text, want in _cases(goldens)
        if _record(list(encoder.encode(text, add_special_tokens=False).ids)) != want
    ]
    assert wrong == []


@pytest.mark.skipif(nexus_native is None, reason="the native extension is not built")
@pytest.mark.parametrize("model", sorted(SETS))
def test_the_native_encoder_gives_the_runtimes_counts(model: str) -> None:
    goldens = SETS[model]
    blob = _blob(goldens)
    cases = _cases(goldens)
    counts = nexus_native.count_parts(str(blob), f"goldens-{model}", [t for _, t, _ in cases])

    assert counts == [count for _, _, (count, _) in cases]
