"""Model reference validation.

The rejection cases matter more than the acceptance cases here. A reference
reaches an HTTP body and, for runtimes without an HTTP API, a subprocess
argument list. These tests pin the boundary so that a later "just let this one
through" change has to break something visible.
"""

from __future__ import annotations

import pytest

from app.adapters.runtime.validation import parse_model_ref
from app.domain.exceptions import InvalidModelReferenceError


@pytest.mark.parametrize(
    ("raw", "registry", "namespace", "name", "tag"),
    [
        ("llama3", None, None, "llama3", None),
        ("qwen2.5-coder:32b", None, None, "qwen2.5-coder", "32b"),
        ("library/qwen2.5", None, "library", "qwen2.5", None),
        ("hf.co/user/repo", "hf.co", "user", "repo", None),
        (
            "registry.ollama.ai/library/llama3:8b-instruct",
            "registry.ollama.ai",
            "library",
            "llama3",
            "8b-instruct",
        ),
    ],
)
def test_accepts_ordinary_references(
    raw: str, registry: str | None, namespace: str | None, name: str, tag: str | None
) -> None:
    ref = parse_model_ref(raw)
    assert (ref.registry, ref.namespace, ref.name, ref.tag) == (registry, namespace, name, tag)
    assert str(ref) == raw, "round trip must preserve the reference exactly"


@pytest.mark.parametrize(
    "raw",
    [
        "llama3; rm -rf /",
        "llama3 && curl evil.example",
        "llama3\nrm -rf /",
        "$(whoami)",
        "`whoami`",
        "llama3|tee /etc/passwd",
    ],
)
def test_rejects_shell_metacharacters(raw: str) -> None:
    """The reason model downloads never build a shell command by
    concatenation. Even so, nothing shaped like this gets past the boundary."""
    with pytest.raises(InvalidModelReferenceError):
        parse_model_ref(raw)


@pytest.mark.parametrize(
    "raw",
    ["../../etc/passwd", "a/../../b", "/absolute/path", "llama3/", "/llama3"],
)
def test_rejects_path_traversal(raw: str) -> None:
    with pytest.raises(InvalidModelReferenceError):
        parse_model_ref(raw)


@pytest.mark.parametrize(
    "raw",
    ["http://evil.example/model", "https://evil.example/model", "file:///etc/passwd"],
)
def test_rejects_urls(raw: str) -> None:
    with pytest.raises(InvalidModelReferenceError):
        parse_model_ref(raw)


def test_rejects_registries_outside_the_allowlist() -> None:
    """Parsing the registry back out of the reference is the only control
    available: Ollama's pull API takes one string and offers no way to
    constrain where it fetches from."""
    with pytest.raises(InvalidModelReferenceError, match="registry not allowed"):
        parse_model_ref("evil.example.com/library/llama3")


@pytest.mark.parametrize("raw", ["", "a" * 256, "UPPERCASE", "-leading-dash", "trailing-dash-"])
def test_rejects_malformed(raw: str) -> None:
    with pytest.raises(InvalidModelReferenceError):
        parse_model_ref(raw)
