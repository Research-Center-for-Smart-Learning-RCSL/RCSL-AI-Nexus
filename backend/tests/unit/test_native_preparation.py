"""Rust preparation avoids constructing a second, large Python vocabulary."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.tokenizer.gguf_token_counter import adapter
from app.adapters.tokenizer.gguf_token_counter.construction import _Vocabulary
from app.adapters.tokenizer.gguf_token_counter.gemma4_renderer import Gemma4Renderer
from tests.unit.exact_token_counting_fixtures import write_store


@pytest.mark.parametrize("architecture,template", [("qwen2", "{{ messages }}"), ("gemma4", None)])
def test_native_success_reads_only_rendering_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, architecture: str, template: str | None
) -> None:
    (tmp_path / "blobs").mkdir()
    blob = write_store(tmp_path, architecture=architecture, template=template)
    counter = adapter.GgufTokenCounter(tmp_path)
    monkeypatch.setattr(
        adapter, "_nexus_native", SimpleNamespace(prepare=lambda *args: (True, None))
    )

    def forbidden(*args):
        raise AssertionError("successful native path built a Python vocabulary")

    monkeypatch.setattr(counter, "_build_python", forbidden)
    real_read = adapter.read_metadata

    def small_read(path, wanted):
        assert not wanted("tokenizer.ggml.tokens")
        assert not wanted("tokenizer.ggml.merges")
        return real_read(path, wanted)

    monkeypatch.setattr(adapter, "read_metadata", small_read)
    vocabulary = counter._build_native("primary:latest", blob)
    assert isinstance(vocabulary, adapter._NativeVocabulary)
    assert vocabulary.renderer is not None
    if architecture == "gemma4":
        assert isinstance(vocabulary.template, Gemma4Renderer)


def test_native_failure_still_builds_python_tokenizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "blobs").mkdir()
    blob = write_store(tmp_path)
    monkeypatch.setattr(
        adapter, "_nexus_native", SimpleNamespace(prepare=lambda *args: (False, "unsupported"))
    )
    counter = adapter.GgufTokenCounter(tmp_path)
    assert isinstance(counter._build_native("primary:latest", blob), _Vocabulary)
