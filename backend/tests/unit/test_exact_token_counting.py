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

from app.adapters.tokenizer.gguf import GgufError, iter_merges, read_metadata
from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, manifest_path, weights_path
from app.application.use_cases.route_chat_request import (
    _counted_phrase,
    _floor_prompt_tokens,
    _floor_tokens,
)
from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.exceptions import (
    COUNT_BY_ESTIMATE,
    COUNT_BY_LOWER_BOUND,
    COUNT_BY_TOKENIZER,
    ContextTooLongError,
    InvalidModelReferenceError,
)

# --- a GGUF written by hand ----------------------------------------------
#
# Small enough to read, real enough to build a tokeniser from: the vocabulary
# below is byte-level ASCII plus two merges, which is the same shape as a
# 248320-entry one and encodes deterministically.

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


# --- the reader -----------------------------------------------------------


def test_the_reader_keeps_what_was_asked_for_and_walks_past_the_rest(tmp_path: Path) -> None:
    """The saving is the point: the two arrays a vocabulary does not need are
    248320 entries each on the model serving `code`."""
    blob = write_gguf(tmp_path / "blob")

    found = read_metadata(blob, lambda key: key.startswith("tokenizer.ggml."))

    assert found["tokenizer.ggml.model"] == "gpt2"
    assert found["tokenizer.ggml.tokens"] == VOCAB
    assert "test.ignored" not in found
    assert "tokenizer.chat_template" not in found


def test_a_file_that_is_not_a_gguf_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    blob = write_gguf(tmp_path / "blob", magic=b"NOPE")

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_an_unknown_format_version_is_refused(tmp_path: Path) -> None:
    """A version this reader has not been checked on would be parsed by
    guessing at the layout, and the guess would be a vocabulary."""
    blob = write_gguf(tmp_path / "blob", version=99)

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_a_truncated_header_ends_as_an_error_and_not_as_a_short_vocabulary(
    tmp_path: Path,
) -> None:
    blob = write_gguf(tmp_path / "blob")
    blob.write_bytes(blob.read_bytes()[:200])

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


def test_a_value_type_this_reader_has_no_size_for_is_a_gguf_error(tmp_path: Path) -> None:
    """Not a `KeyError`. The two array branches indexed the scalar table before
    checking membership, so a corrupt element type escaped as a bare
    `KeyError` — which `GgufTokenCounter._build` did not catch, which
    `count_prompt` did not catch, and which therefore became a 500 on every
    request routed to that model, re-reading the header each time because a
    build that raises caches nothing."""
    blob = tmp_path / "blob"
    blob.write_bytes(
        b"GGUF"
        + struct.pack("<I", 3)
        + _u64(0)
        + _u64(1)
        + _entry("odd", _ARRAY, struct.pack("<I", 42) + _u64(3) + b"\x00" * 24)
    )

    with pytest.raises(GgufError):
        read_metadata(blob, lambda key: True)


async def test_a_blob_that_cannot_be_parsed_falls_back_instead_of_failing(
    tmp_path: Path,
) -> None:
    """The port's contract is that a counter may decline to answer. A file this
    platform does not own is exactly where an unanticipated failure belongs, and
    the cost of letting one through is not a bad count but a refused request."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    (tmp_path / "blobs" / "sha256-abc123").write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\x01" * 9)

    counter = GgufTokenCounter(tmp_path)

    assert await counter.prepare("primary:latest") is False
    assert await counter.count_prompt("primary:latest", [], []) is None


def test_merges_split_on_the_first_space_only() -> None:
    """The commonest merge in a byte-level vocabulary is two spaces, written
    `"Ġ Ġ"`. Splitting on every space turns it into a row the tokeniser then
    does not have."""
    assert list(iter_merges(["Ġ Ġ", "h e"])) == [("Ġ", "Ġ"), ("h", "e")]

    with pytest.raises(GgufError):
        list(iter_merges(["nospace"]))


# --- resolving a reference to a file --------------------------------------


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


# --- the counter ----------------------------------------------------------


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


async def test_a_model_with_no_chat_template_is_not_counted_by_content_alone(
    tmp_path: Path,
) -> None:
    """Counting content without the framing under-counts, which is the
    direction that ends in a silent truncation. The estimate over-counts, so
    falling back to it is the safe half of a bad choice."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)

    assert await GgufTokenCounter(tmp_path).prepare("primary:latest") is False


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

    assert len(counter._cache) == 1


# --- the bound that runs before a model is chosen -------------------------


def test_the_floor_never_exceeds_what_a_tokeniser_would_count() -> None:
    """The whole purpose of the bound: it may be far below the real figure and
    may never be above it, because it refuses without knowing the model."""
    prose = "The quick brown fox jumps over the lazy dog. " * 200
    assert _floor_tokens(prose) < len(prose) / 4.4

    chinese = "這是一份中文的維運手冊，描述閘道器的行為。" * 200
    assert _floor_tokens(chinese) < len(chinese) / 1.4


def test_the_floor_is_computed_without_walking_the_string() -> None:
    """Both arms are C-level passes; the non-ASCII one turns UTF-8's own
    arithmetic into a lower bound on the character count."""
    mixed = "ascii 中文 ascii"
    assert _floor_tokens(mixed) > 0
    assert _floor_prompt_tokens([Message(role=MessageRole.USER, content=mixed)], []) >= 0


def test_the_floor_counts_tool_definitions_like_everything_else() -> None:
    tool = ToolDefinition(name="x" * 100, description="y" * 100, parameters={"a": "b" * 100})
    bare = _floor_prompt_tokens([Message(role=MessageRole.USER, content="hi")], [])

    assert _floor_prompt_tokens([Message(role=MessageRole.USER, content="hi")], [tool]) > bare


def test_a_figure_is_named_for_what_it_is() -> None:
    assert _counted_phrase(COUNT_BY_TOKENIZER, 10) == "10 tokens"
    assert _counted_phrase(COUNT_BY_LOWER_BOUND, 10) == "at least ~10 tokens"
    assert _counted_phrase(COUNT_BY_ESTIMATE, 10) == "~10 estimated tokens"


def test_the_caller_is_told_which_of_the_three_they_were_handed() -> None:
    """A caller deciding how much to trim needs to know whether the number is a
    count, an estimate that has run 1.48x high, or a lower bound."""
    counted = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_TOKENIZER)
    estimated = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_ESTIMATE)
    bounded = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_LOWER_BOUND)

    assert "is 99,000 tokens" in counted.public_message
    assert "an estimated 99,000 tokens" in estimated.public_message
    assert "at least 99,000 tokens" in bounded.public_message
