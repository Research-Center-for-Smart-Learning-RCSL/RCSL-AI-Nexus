from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, manifest_path, weights_path
from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.exceptions import (
    InvalidModelReferenceError,
)
from tests.unit.exact_token_counting_fixtures import (
    write_store,
)

pytest_plugins = ("tests.unit.exact_token_counting_fixtures",)


def test_a_reference_resolves_through_the_manifest_to_its_blob(store: Path) -> None:
    assert weights_path(store, "primary:latest").name == "sha256-abc123"


def test_defaults_are_filled_in_the_way_the_runtime_fills_them(tmp_path: Path) -> None:
    assert manifest_path(tmp_path, "qwen3.6:35b").parts[-4:] == (
        "registry.ollama.ai",
        "library",
        "qwen3.6",
        "35b",
    )


def test_a_reference_this_host_does_not_hold_is_a_missing_file_not_another_model(
    store: Path,
) -> None:
    """The whole argument for reading the weights rather than asking the
    runtime: a binding that is wrong fails to open a file."""
    with pytest.raises(BlobNotFound):
        weights_path(store, "somebody-else:latest")


def test_a_reference_that_could_escape_the_store_is_refused_by_the_grammar(store: Path) -> None:
    with pytest.raises(InvalidModelReferenceError):
        weights_path(store, "../../etc/passwd")


def test_a_digest_carrying_a_path_separator_is_refused(tmp_path: Path) -> None:
    """Read out of a file another process writes, and then used to build a
    path."""
    (tmp_path / "blobs").mkdir(parents=True)
    manifest = manifest_path(tmp_path, "evil:latest")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "a:../../x"}]}
        )
    )

    with pytest.raises(BlobNotFound):
        weights_path(tmp_path, "evil:latest")


def test_a_manifest_with_no_model_layer_is_not_a_model(tmp_path: Path) -> None:
    manifest = manifest_path(tmp_path, "config-only:latest")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"layers": [{"mediaType": "text/plain", "digest": "sha256:a"}]}))

    with pytest.raises(BlobNotFound):
        weights_path(tmp_path, "config-only:latest")


async def test_the_count_includes_the_framing_the_runtime_wraps_around_it(store: Path) -> None:
    """Not the sum of the message contents. The template's role markers are
    tokens the model reads and the context charges for."""
    counter = GgufTokenCounter(store)

    total = await counter.count_prompt(
        "primary:latest", [Message(role=MessageRole.USER, content="hello")], []
    )
    parts = await counter.count_parts("primary:latest", ["hello"])

    assert total is not None and parts is not None
    assert total > parts[0]


async def test_tool_definitions_are_counted_and_not_adjusted_for(store: Path) -> None:
    """122870 of one refused payload's 140059 tokens were 286 definitions."""
    counter = GgufTokenCounter(store)
    messages = [Message(role=MessageRole.USER, content="hello")]
    tool = ToolDefinition(name="read", description="reads", parameters={"type": "object"})

    without = await counter.count_prompt("primary:latest", messages, [])
    with_tools = await counter.count_prompt("primary:latest", messages, [tool])

    assert without is not None and with_tools is not None
    assert with_tools > without


async def test_a_reference_with_no_weights_on_this_host_says_so_rather_than_guessing(
    store: Path,
) -> None:
    counter = GgufTokenCounter(store)

    assert await counter.count_prompt("absent:latest", [], []) is None
    assert await counter.count_parts("absent:latest", ["hello"]) is None
    assert await counter.prepare("absent:latest") is False


async def test_an_unmeasured_pre_tokeniser_falls_back_rather_than_splitting_by_guess(
    tmp_path: Path,
) -> None:
    """A vocabulary that splits text the wrong way produces a confident figure
    nothing here would notice was wrong."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, pre="something-nobody-measured")

    assert await GgufTokenCounter(tmp_path).prepare("primary:latest") is False


async def test_a_model_with_no_chat_template_uses_the_chatml_fallback(
    tmp_path: Path,
) -> None:
    """A model without an embedded chat template falls back to ChatML, which
    is the template Ollama applies via ``--chat-template chatml`` for models
    like gemma4. The fallback means the framing overhead IS counted, so the
    previous concern about under-counting without framing no longer applies."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)

    counter = GgufTokenCounter(tmp_path)
    assert await counter.prepare("primary:latest") is True
    count = await counter.count_prompt(
        "primary:latest",
        [Message(role=MessageRole.USER, content="hello")],
        [],
    )
    assert count is not None and count > 0


async def test_a_failed_resolution_is_remembered_rather_than_retried(store: Path) -> None:
    """Retrying means reading a header of tens of megabytes on every request to
    a model that will never have one."""
    counter = GgufTokenCounter(store)
    assert await counter.prepare("absent:latest") is False

    write_store(store, "absent:latest")

    assert await counter.count_prompt("absent:latest", [], []) is None, "cached, not retried"
    assert await counter.prepare("absent:latest") is True, "prepare is what clears it"


async def test_the_cache_holds_only_what_it_was_sized_for(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, "one:latest")
    write_store(tmp_path, "two:latest")
    counter = GgufTokenCounter(tmp_path, cache_size=1)

    assert await counter.prepare("one:latest") is True
    assert await counter.prepare("two:latest") is True

    if counter._use_native:
        pytest.skip("Rust backend manages its own bounded cache")
    assert len(counter._cache) == 1
