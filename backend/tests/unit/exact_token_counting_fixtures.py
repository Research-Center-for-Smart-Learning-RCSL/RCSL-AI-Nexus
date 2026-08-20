"""Counting a prompt with the model's own vocabulary instead of estimating it.

The case these pin is one refused request, not a general inefficiency. On
2026-08-17 a client was turned away at 140059 estimated tokens against a 122880
ceiling; the payload was about 99000 real ones, and the model that would have
served it could read 131072. It was refused by the estimator rather than by the
hardware, and every test here is some part of why that can no longer happen.

Nothing in this file talks to a runtime. What it cannot check is the one thing
only the runtime can answer — whether the count equals `prompt_eval_count` —
which is why `_log_estimate_drift` compares the two on every request in
production and why the measurements are recorded in the module docstring of
`adapters/tokenizer/gguf_token_counter.py` rather than asserted here.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.adapters.tokenizer.ollama_blobs import manifest_path

_STRING, _ARRAY, _UINT32 = 8, 9, 4

ALPHABET = [chr(c) for c in range(33, 127)] + ["Ġ", "Ċ"]

VOCAB = [*ALPHABET, "he", "hel", "<|im_start|>", "<|im_end|>"]

MERGES = ["h e", "he l"]

CONTROL = {"<|im_start|>", "<|im_end|>"}

TEMPLATE = (
    "{%- for m in messages %}{{- '<|im_start|>' + m.role + '\\n' + m.content + '<|im_end|>' }}"
    "{%- endfor %}{%- if tools %}{%- for t in tools %}{{- t | tojson }}{%- endfor %}{%- endif %}"
)


def _u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def _string(text: str) -> bytes:
    raw = text.encode()
    return _u64(len(raw)) + raw


def _entry(key: str, type_id: int, payload: bytes) -> bytes:
    return _string(key) + struct.pack("<I", type_id) + payload


def _string_array(values: Sequence[str]) -> bytes:
    return struct.pack("<I", _STRING) + _u64(len(values)) + b"".join(_string(v) for v in values)


def _int_array(values: Sequence[int]) -> bytes:
    return (
        struct.pack("<I", _UINT32)
        + _u64(len(values))
        + b"".join(struct.pack("<I", v) for v in values)
    )


def write_gguf(
    path: Path,
    *,
    tokens: Sequence[str] = tuple(VOCAB),
    merges: Sequence[str] = tuple(MERGES),
    pre: str = "qwen2",
    model: str = "gpt2",
    template: str | None = TEMPLATE,
    version: int = 3,
    magic: bytes = b"GGUF",
) -> Path:
    types = [3 if t in CONTROL else 1 for t in tokens]
    entries = [
        _entry("general.architecture", _STRING, _string("test")),
        # A key nothing wants, carrying an array large enough that keeping it
        # would be visible: this is what `skip_value` exists to walk past.
        _entry("test.ignored", _ARRAY, _int_array(list(range(1000)))),
        _entry("tokenizer.ggml.model", _STRING, _string(model)),
        _entry("tokenizer.ggml.pre", _STRING, _string(pre)),
        _entry("tokenizer.ggml.tokens", _ARRAY, _string_array(tokens)),
        _entry("tokenizer.ggml.merges", _ARRAY, _string_array(merges)),
        _entry("tokenizer.ggml.token_type", _ARRAY, _int_array(types)),
    ]
    if template is not None:
        entries.append(_entry("tokenizer.chat_template", _STRING, _string(template)))
    body = magic + struct.pack("<I", version) + _u64(0) + _u64(len(entries)) + b"".join(entries)
    path.write_bytes(body + b"\x00" * 64)
    return path


def write_store(root: Path, ref: str = "primary:latest", **kwargs: object) -> Path:
    """A model store shaped the way Ollama's is: a manifest naming a blob."""
    blob = write_gguf(root / "blobs" / "sha256-abc123", **kwargs)  # type: ignore[arg-type]
    manifest = manifest_path(root, ref)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:zzz"},
                    {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc123"},
                ]
            }
        )
    )
    return blob


@pytest.fixture
def store(tmp_path: Path) -> Path:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    return tmp_path
