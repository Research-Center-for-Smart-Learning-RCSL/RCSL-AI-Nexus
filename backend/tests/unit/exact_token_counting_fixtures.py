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

_STRING, _ARRAY, _UINT32, _INT32, _FLOAT32 = 8, 9, 4, 5, 6

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


def _int32_array(values: Sequence[int]) -> bytes:
    return (
        struct.pack("<I", _INT32)
        + _u64(len(values))
        + b"".join(struct.pack("<i", v) for v in values)
    )


def _float_array(values: Sequence[float]) -> bytes:
    return (
        struct.pack("<I", _FLOAT32)
        + _u64(len(values))
        + b"".join(struct.pack("<f", v) for v in values)
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
    context_length: int | None = None,
    scores: Sequence[float] | None = None,
    token_types_as_int32: bool = True,
    architecture: str = "test",
    control: Sequence[str] = tuple(CONTROL),
) -> Path:
    """A GGUF header carrying only what the counter reads.

    Token types are written as INT32 by default because that is what every
    real file on the production host carries; the UINT32 this fixture used to
    write is what let the Rust reader drop every control token unnoticed until
    2026-10-08 (#24). `scores` makes a `model: llama` (SentencePiece) file.
    """
    types = [3 if t in control else 1 for t in tokens]
    types_array = _int32_array(types) if token_types_as_int32 else _int_array(types)
    entries = [
        _entry("general.architecture", _STRING, _string(architecture)),
        # A key nothing wants, carrying an array large enough that keeping it
        # would be visible: this is what `skip_value` exists to walk past.
        _entry("test.ignored", _ARRAY, _int_array(list(range(1000)))),
        _entry("tokenizer.ggml.model", _STRING, _string(model)),
        _entry("tokenizer.ggml.pre", _STRING, _string(pre)),
        _entry("tokenizer.ggml.tokens", _ARRAY, _string_array(tokens)),
        _entry("tokenizer.ggml.merges", _ARRAY, _string_array(merges)),
        _entry("tokenizer.ggml.token_type", _ARRAY, types_array),
    ]
    if scores is not None:
        entries.append(_entry("tokenizer.ggml.scores", _ARRAY, _float_array(scores)))
    if template is not None:
        entries.append(_entry("tokenizer.chat_template", _STRING, _string(template)))
    if context_length is not None:
        # Under the architecture's own prefix, as every real header carries it:
        # `qwen2.context_length`, `gemma4.context_length`, one per family. The
        # reader matches the suffix precisely because the prefix is not fixed.
        entries.append(_entry("test.context_length", _UINT32, struct.pack("<I", context_length)))
    body = magic + struct.pack("<I", version) + _u64(0) + _u64(len(entries)) + b"".join(entries)
    path.write_bytes(body + b"\x00" * 64)
    return path


def write_store(
    root: Path, ref: str = "primary:latest", digest: str = "abc123", **kwargs: object
) -> Path:
    """A model store shaped the way Ollama's is: a manifest naming a blob.

    `digest` places the blob and names it in the manifest, so a test can
    repoint a tag at different weights, which is what a same-tag pull does.
    """
    blob = write_gguf(root / "blobs" / f"sha256-{digest}", **kwargs)  # type: ignore[arg-type]
    manifest = manifest_path(root, ref)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:zzz"},
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": f"sha256:{digest}",
                    },
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
