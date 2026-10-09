"""Which counting code produced a count (PR2b on #24, review point 1).

A validated profile says "this code counts this model at least as high as the
runtime". It has to name the code, not a version string a person remembers to
bump: these are digests of the encoder's and renderer's own source, so any
change to them withdraws every record until it is measured again.

- **Encoder**, per backend: the Python modules that build and run the
  vocabulary, with the `tokenizers` library's version; or the native
  extension's source digest, baked in at build time by `native/build.rs`.
- **Renderer**: the chat template's own text with the module that renders it,
  or the gemma4 port's source. The ChatML fallback is never a renderer that
  can be validated: it is a guess at a format the runtime does not use.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PYTHON_ENCODER_SOURCES = ("construction.py", "constants.py", "gemma4_bpe.py")


def _digest(*parts: bytes) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()[:16]


def _source(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@cache
def python_encoder() -> str:
    import tokenizers

    return "python:" + _digest(
        *(_source(name) for name in PYTHON_ENCODER_SOURCES),
        f"tokenizers=={tokenizers.__version__}".encode(),
    )


def native_encoder(source_digest: str) -> str:
    return f"native:{source_digest}"


@cache
def jinja_renderer(template: str) -> str:
    return "jinja:" + _digest(template.encode(), _source("templates.py"))


@cache
def gemma4_renderer(variant: str) -> str:
    return f"gemma4-port-{variant}:" + _digest(_source("gemma4_renderer.py"))
