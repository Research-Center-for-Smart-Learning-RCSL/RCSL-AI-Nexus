"""Model reference parsing and registry allowlisting.

This sits at the adapter boundary rather than in a router, so every path that
can reach a runtime passes through it, including background download jobs and
anything added later.

Ollama's pull endpoint takes a single `name` string with the registry embedded
in it, and offers no separate parameter to constrain. The registry therefore
has to be parsed back out of the reference and checked explicitly; there is no
API-level way to say "only pull from here".

See docs/architecture/security.md section 7.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.exceptions import InvalidModelReferenceError

_SEGMENT = r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?"

MODEL_REF = re.compile(
    rf"^(?:(?P<registry>{_SEGMENT}(?:\.{_SEGMENT})+)/)?"  # optional registry host
    rf"(?:(?P<namespace>{_SEGMENT})/)?"  # optional namespace
    rf"(?P<name>{_SEGMENT})"
    rf"(?::(?P<tag>[a-zA-Z0-9._-]{{1,64}}))?$"
)

ALLOWED_REGISTRIES = frozenset({"registry.ollama.ai", "huggingface.co", "hf.co"})
"""An earlier draft used a pattern that disallowed `/` entirely, which rejected
ordinary references such as `library/qwen2.5` and left this allowlist
unreachable, so nothing was ever actually constrained."""

MAX_REF_LENGTH = 255


@dataclass(frozen=True, slots=True)
class ModelReference:
    registry: str | None
    namespace: str | None
    name: str
    tag: str | None

    def __str__(self) -> str:
        parts = [p for p in (self.registry, self.namespace, self.name) if p]
        joined = "/".join(parts)
        return f"{joined}:{self.tag}" if self.tag else joined


def parse_model_ref(raw: str) -> ModelReference:
    """Parse and validate, or raise `InvalidModelReferenceError`.

    Rejecting is the point. A reference reaches a subprocess argument list or
    an HTTP body, and a value containing shell metacharacters, path traversal,
    or a URL is the difference between a download and host code execution.
    """
    if not raw or len(raw) > MAX_REF_LENGTH:
        raise InvalidModelReferenceError(detail=f"length out of range: {len(raw)}")

    match = MODEL_REF.fullmatch(raw)
    if match is None:
        raise InvalidModelReferenceError(detail=f"does not match the reference grammar: {raw!r}")

    registry = match.group("registry")
    if registry is not None and registry not in ALLOWED_REGISTRIES:
        raise InvalidModelReferenceError(detail=f"registry not allowed: {registry}")

    return ModelReference(
        registry=registry,
        namespace=match.group("namespace"),
        name=match.group("name"),
        tag=match.group("tag"),
    )


def assert_valid_model_ref(raw: str) -> str:
    """Validate and return the reference unchanged, for call sites that only
    need the guard and pass the original string onward."""
    parse_model_ref(raw)
    return raw
