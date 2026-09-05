"""Tests for the Rust nexus_native extension, mirroring the Python GGUF tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from tests.unit.exact_token_counting_fixtures import (
    VOCAB,
    write_gguf,
    write_store,
)

nexus_native = pytest.importorskip("nexus_native")


def test_read_gguf_metadata_keeps_wanted_keys(tmp_path: Path) -> None:
    blob = write_gguf(tmp_path / "blob")
    found = nexus_native.read_gguf_metadata(str(blob))
    assert found["tokenizer.ggml.model"] == "gpt2"
    assert found["tokenizer.ggml.tokens"] == VOCAB
    assert "test.ignored" in found


def test_read_gguf_refuses_bad_magic(tmp_path: Path) -> None:
    blob = write_gguf(tmp_path / "blob", magic=b"NOPE")
    with pytest.raises(RuntimeError):
        nexus_native.read_gguf_metadata(str(blob))


def test_read_gguf_refuses_unknown_version(tmp_path: Path) -> None:
    blob = write_gguf(tmp_path / "blob", version=99)
    with pytest.raises(RuntimeError):
        nexus_native.read_gguf_metadata(str(blob))


def test_prepare_and_count_prompt(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    success, error = nexus_native.prepare(blob_path, "test-ref")
    assert success is True
    assert error is None

    messages = [{"role": "user", "content": "hello"}]
    tools: list[object] = []
    result = nexus_native.count_prompt(
        blob_path, "test-ref", json.dumps(messages), json.dumps(tools)
    )
    assert result is not None
    assert isinstance(result, int)
    assert result > 0


def test_prepare_returns_error_message_on_failure(tmp_path: Path) -> None:
    bad_blob = tmp_path / "bad.gguf"
    bad_blob.write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\x01" * 9)

    success, error = nexus_native.prepare(str(bad_blob), "fail-ref")
    assert success is False
    assert error is not None
    assert isinstance(error, str)
    assert len(error) > 0


def test_count_prompt_returns_none_for_unparseable_blob(tmp_path: Path) -> None:
    bad_blob = tmp_path / "bad.gguf"
    bad_blob.write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\x01" * 9)

    result = nexus_native.count_prompt(
        str(bad_blob), "bad-ref", json.dumps([{"role": "user", "content": "hi"}]), "[]"
    )
    assert result is None


def test_count_parts(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    nexus_native.prepare(blob_path, "parts-ref")

    result = nexus_native.count_parts(blob_path, "parts-ref", ["hello", "world"])
    assert result is not None
    assert len(result) == 2
    assert all(isinstance(c, int) and c > 0 for c in result)


def test_evict_clears_cache(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    nexus_native.prepare(blob_path, "evict-ref")
    nexus_native.evict("evict-ref")

    result = nexus_native.count_parts(blob_path, "evict-ref", ["test"])
    assert result is not None


def test_count_matches_python_tokenizer(tmp_path: Path) -> None:
    """The Rust tokenizer should produce the same count as the Python one."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    # Rust path
    nexus_native.prepare(blob_path, "compare-ref")
    messages = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "hi there"},
    ]
    rust_count = nexus_native.count_prompt(blob_path, "compare-ref", json.dumps(messages), "[]")

    # Python path
    from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter

    counter = GgufTokenCounter(tmp_path)

    from app.domain.entities.chat import Message, MessageRole

    py_messages = [
        Message(role=MessageRole.USER, content="hello world"),
        Message(role=MessageRole.ASSISTANT, content="hi there"),
    ]
    import asyncio

    py_count = asyncio.run(counter.count_prompt("primary:latest", py_messages, []))

    assert rust_count is not None
    assert py_count is not None
    assert rust_count == py_count


def test_count_with_tools_matches_python(tmp_path: Path) -> None:
    """Tool definitions must preserve key order (serde_json preserve_order)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    nexus_native.prepare(blob_path, "tools-ref")

    tools = [
        {"type": "function", "function": {"name": "get_weather", "parameters": {"city": "string"}}},
        {"type": "function", "function": {"name": "search", "parameters": {"query": "string"}}},
    ]
    messages = [{"role": "user", "content": "what is the weather?"}]

    rust_count = nexus_native.count_prompt(
        blob_path, "tools-ref", json.dumps(messages), json.dumps(tools)
    )
    assert rust_count is not None
    assert rust_count > 0


def test_no_chat_template_still_counts(tmp_path: Path) -> None:
    """A GGUF with no chat_template key should use the ChatML fallback."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)
    blob_path = str(tmp_path / "blobs" / "sha256-abc123")

    success, _ = nexus_native.prepare(blob_path, "no-tmpl-ref")
    assert success is True

    messages = [{"role": "user", "content": "hello"}]
    result = nexus_native.count_prompt(blob_path, "no-tmpl-ref", json.dumps(messages), "[]")
    assert result is not None
    assert result > 0
