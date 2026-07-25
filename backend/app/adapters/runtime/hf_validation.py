"""HuggingFace repository id parsing for the MLX runtime.

The MLX adapter takes a HuggingFace repository id (`mlx-community/Qwen2.5-7B-Instruct-4bit`),
not the `namespace/name:tag` reference Ollama uses, which is why validation lives
per-adapter rather than in a shared helper. See `ModelRuntimePort.validate_ref`.

The same reasoning as validation.py applies: this value reaches
`snapshot_download(repo_id=...)`, so a repository id containing path traversal or
a URL is the difference between a download and reading somewhere it should not.
The id is never passed to a shell. See docs/architecture/security.md section 7.1.
"""

from __future__ import annotations

import re

from app.domain.exceptions import InvalidModelReferenceError

_HF_SEGMENT = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"

HF_REPO_ID = re.compile(rf"^(?:{_HF_SEGMENT}/)?{_HF_SEGMENT}$")
"""At most one `/`, so `namespace/name` or a bare canonical `name`. Each segment
starts and ends alphanumeric, which rules out a leading `/`, a trailing dot, and
the `.git` suffix without special-casing them."""

MAX_HF_REPO_ID_LENGTH = 96 * 2 + 1
"""HuggingFace limits each of the namespace and name to 96 characters."""


def assert_valid_hf_repo_id(raw: str) -> str:
    """Validate a HuggingFace repository id, or raise `InvalidModelReferenceError`.

    Returns the id unchanged so call sites can guard and pass it onward in one
    expression, matching `assert_valid_model_ref`.
    """
    if not raw or len(raw) > MAX_HF_REPO_ID_LENGTH:
        raise InvalidModelReferenceError(detail=f"length out of range: {len(raw)}")

    # Explicit even though the grammar largely prevents it: a `.` is legal inside
    # a segment (`Qwen2.5`), so `..` would otherwise slip through, and `..` in a
    # repo id is the path-traversal case this guard exists for.
    if ".." in raw:
        raise InvalidModelReferenceError(detail="'..' is not allowed in a repository id")

    if HF_REPO_ID.fullmatch(raw) is None:
        raise InvalidModelReferenceError(
            detail=f"does not match the HuggingFace repository id grammar: {raw!r}"
        )

    return raw
