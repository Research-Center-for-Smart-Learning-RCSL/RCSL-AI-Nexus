"""Checkout line endings do not change Python's loaded counting code."""

from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter import fingerprint


def test_crlf_checkout_preserves_the_lf_encoder_and_renderer_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = (*fingerprint.PYTHON_ENCODER_SOURCES, "templates.py", "gemma4_renderer.py")
    sources = {name: fingerprint._source(name) for name in names}
    expected_encoder = fingerprint.python_encoder()
    expected_jinja = fingerprint.jinja_renderer("{{ messages }}")
    expected_gemma = fingerprint.gemma4_renderer("large")
    for name, source in sources.items():
        (tmp_path / name).write_bytes(source.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(fingerprint, "_HERE", tmp_path)
    fingerprint.python_encoder.cache_clear()
    fingerprint.jinja_renderer.cache_clear()
    fingerprint.gemma4_renderer.cache_clear()
    try:
        assert fingerprint.python_encoder() == expected_encoder
        assert fingerprint.jinja_renderer("{{ messages }}") == expected_jinja
        assert fingerprint.gemma4_renderer("large") == expected_gemma
    finally:
        fingerprint.python_encoder.cache_clear()
        fingerprint.jinja_renderer.cache_clear()
        fingerprint.gemma4_renderer.cache_clear()
