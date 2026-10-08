from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, manifest_path, weights_path
from app.domain.entities.chat import Message, MessageRole, ToolCall, ToolDefinition
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
    """A model without an embedded chat template is counted through ChatML, so
    some framing is counted rather than none. It is a stand-in, not the
    runtime's format: gemma4 is rendered by a built-in renderer in its own
    format (`render_diff.py`, 2026-10-08, #24), and the counts agree on plain
    messages only approximately."""
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


async def test_a_failed_resolution_is_remembered_until_the_reference_changes(
    store: Path,
) -> None:
    """Retrying means reading a header of tens of megabytes on every request to
    a model that will never have one, so a failure is remembered while the
    reference still names the same thing. Once a manifest appears, the
    reference names something new and is resolved again, without waiting for
    `prepare` (review on #24: caches follow the weights, not the tag)."""
    counter = GgufTokenCounter(store)
    assert await counter.prepare("absent:latest") is False
    assert await counter.count_prompt("absent:latest", [], []) is None, "remembered"

    write_store(store, "absent:latest")

    assert await counter.count_prompt("absent:latest", [], []) is not None, "re-resolved"


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


# --- what the model says about itself ------------------------------------


async def test_the_declared_context_is_read_from_the_model_and_not_the_registry(
    tmp_path: Path,
) -> None:
    """The registry's figure is a claim; this one is the model's own.

    On 2026-09-07 `qwen7b` was registered at 262144 against a declared 32768,
    and every guard trusting the registration was eight times too permissive —
    including the one added on 2026-08-17 to stop silent truncation.
    """
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, context_length=32768)
    counter = GgufTokenCounter(tmp_path)

    assert await counter.native_context_length("primary:latest") == 32768


async def test_a_header_that_declares_nothing_says_so(tmp_path: Path) -> None:
    """`None` is cannot-say, as everywhere on this port. A caller must fall
    back to the registered figure rather than to no bound at all, so an absent
    key has to be distinguishable from a small one."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path)
    counter = GgufTokenCounter(tmp_path)

    assert await counter.native_context_length("primary:latest") is None


async def test_a_reference_with_no_blob_says_cannot_say_rather_than_raising(
    tmp_path: Path,
) -> None:
    """An MLX model, or one registered but not pulled. Reading its context must
    not be the thing that fails a request."""
    counter = GgufTokenCounter(tmp_path)

    assert await counter.native_context_length("absent:latest") is None


async def test_the_declared_context_is_read_once_per_reference(tmp_path: Path) -> None:
    """Cached beside the vocabulary and separately from it: the two are wanted
    at different moments, and this one must not cost a header scan on every
    summarisation."""
    (tmp_path / "blobs").mkdir(parents=True)
    blob = write_store(tmp_path, context_length=8192)
    counter = GgufTokenCounter(tmp_path)

    assert await counter.native_context_length("primary:latest") == 8192
    blob.unlink()
    assert await counter.native_context_length("primary:latest") == 8192


async def test_the_declared_context_cache_is_not_sized_for_vocabularies(
    tmp_path: Path,
) -> None:
    """Two caches, bounded for different reasons.

    A vocabulary is 132 MB resident and its ceiling is the memory budget this
    deployment is designed around. A declared context length is an integer, and
    what fills that cache is `/admin/model-reference` being typed into: a
    register form walks it through every prefix of a reference — `gem`, `gemm`,
    `gemma` — so at the vocabulary's size of two the real models' figures were
    evicted before the operator finished the word.
    """
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, context_length=32768)
    counter = GgufTokenCounter(tmp_path, cache_size=2)

    assert await counter.native_context_length("primary:latest") == 32768
    # Every prefix a form would ask about, none of which resolves.
    for i in range(20):
        assert await counter.native_context_length(f"partial-{i}:latest") is None

    # Still remembered, without going back to disk: the blob is gone.
    (tmp_path / "blobs" / "sha256-abc123").unlink()
    assert await counter.native_context_length("primary:latest") == 32768


def _a_tool_call(arguments: str) -> list[Message]:
    return [
        Message(role=MessageRole.USER, content="read it"),
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=(ToolCall("call_1", "read_file", arguments),),
        ),
        Message(role=MessageRole.TOOL, content="x = 1", tool_call_id="call_1", name="read_file"),
    ]


async def test_the_fallback_template_counts_tool_call_arguments(tmp_path: Path) -> None:
    """ChatML renders no assistant tool call, so through it the count was the
    same for an 8- and a 32,768-character argument: an under-count of unknown
    size, presented as exact (review on #24). The calls are now encoded and
    added, so the count grows with the arguments."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)
    counter = GgufTokenCounter(tmp_path)

    short = await counter.count_prompt("primary:latest", _a_tool_call('{"path":"a"}'), [])
    long = await counter.count_prompt(
        "primary:latest", _a_tool_call('{"path":"' + "abcdefgh" * 4096 + '"}'), []
    )

    assert short is not None and long is not None
    assert long - short >= 4096, (short, long)


async def test_the_fallback_template_still_counts_turns_without_tool_calls(
    tmp_path: Path,
) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)

    count = await GgufTokenCounter(tmp_path).count_prompt(
        "primary:latest", [Message(role=MessageRole.USER, content="hello")], []
    )

    assert count is not None and count > 0


async def test_a_model_with_its_own_template_still_counts_tool_calls(store: Path) -> None:
    """Only the fallback declines; a template from the GGUF renders the calls."""
    count = await GgufTokenCounter(store).count_prompt(
        "primary:latest", _a_tool_call('{"path":"a"}'), []
    )

    assert count is not None


async def test_a_tool_call_that_cannot_be_encoded_gives_no_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rendered prompt encodes, but one call's arguments do not: the count
    must be None, not the rendered part alone. The native wrapper's `encode`
    turned a failure into 0, which made exactly that partial count (review on
    #28)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)
    counter = GgufTokenCounter(tmp_path)
    assert await counter.count_prompt(
        "primary:latest", [Message(role=MessageRole.USER, content="hello")], []
    )

    async def failing_parts(ref: str, texts: object) -> None:
        return None

    monkeypatch.setattr(counter, "count_parts", failing_parts)

    assert await counter.count_prompt("primary:latest", _a_tool_call('{"path":"a"}'), []) is None


async def test_a_native_encoding_failure_is_not_counted_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same, through the Rust extension itself: `encode_texts` reports
    a failed part as None, and that has to reach the caller."""
    adapter = pytest.importorskip("app.adapters.tokenizer.gguf_token_counter.adapter")
    if adapter._nexus_native is None:
        pytest.skip("nexus_native is not installed")
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None)
    counter = GgufTokenCounter(tmp_path)
    assert await counter.count_prompt(
        "primary:latest", [Message(role=MessageRole.USER, content="hello")], []
    )
    monkeypatch.setattr(adapter._nexus_native, "encode_texts", lambda *args: None)

    assert await counter.count_prompt("primary:latest", _a_tool_call('{"path":"a"}'), []) is None


async def test_gemma4_without_a_template_is_rendered_as_the_runtime_renders_it(
    tmp_path: Path,
) -> None:
    """Not ChatML: the runtime's own gemma4 format, ported (C6c, #24). The
    tool call is in the rendering, so its arguments are counted by the
    format itself rather than added on afterwards."""
    from app.adapters.tokenizer.gguf_token_counter.gemma4_renderer import Gemma4Renderer

    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, ref="gemma4:31b-it-q8_0", template=None, architecture="gemma4")
    counter = GgufTokenCounter(tmp_path)

    vocabulary = await counter._vocabulary("gemma4:31b-it-q8_0")  # noqa: SLF001
    short = await counter.count_prompt("gemma4:31b-it-q8_0", _a_tool_call('{"path":"a"}'), [])
    long = await counter.count_prompt(
        "gemma4:31b-it-q8_0", _a_tool_call('{"path":"' + "abcdefgh" * 512 + '"}'), []
    )

    assert vocabulary is not None
    assert isinstance(vocabulary.template, Gemma4Renderer)
    assert "gemma4:31b-it-q8_0" not in counter._fallback_template  # noqa: SLF001
    assert short is not None and long is not None
    assert long - short >= 512, (short, long)


async def test_another_architecture_without_a_template_still_falls_back(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, template=None, architecture="llama")
    counter = GgufTokenCounter(tmp_path)

    assert await counter.count_prompt(
        "primary:latest", [Message(role=MessageRole.USER, content="hello")], []
    )
    assert "primary:latest" in counter._fallback_template  # noqa: SLF001


async def test_an_unencodable_character_gives_no_count_on_the_python_backend(
    tmp_path: Path,
) -> None:
    """The review on #29: on the Python backend a Unigram vocabulary with no
    unk piece raises on U+10FFFF, and the gemma4 path let that escape, so the
    guard aborted instead of using its estimate. It is None now, on every path
    that encodes through `count_parts`."""
    control = ["<bos>", "<|turn>", "<turn|>", "<|think|>", "<|channel>", "<channel|>"]
    words = ["system", "user", "model", "thought", "hello", "\n", "▁"]
    singles = sorted(set("".join(words)) - {"▁", "\n"})
    pieces = {**{t: -1.0 for t in control}, **{w: -2.0 for w in words}}
    pieces |= {c: -8.0 for c in singles}
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(
        tmp_path,
        ref="gemma4:31b-it-q8_0",
        tokens=list(pieces),
        scores=list(pieces.values()),
        model="llama",
        pre="gemma4",
        merges=(),
        template=None,
        architecture="gemma4",
        control=control,
    )
    counter = GgufTokenCounter(tmp_path)
    counter._use_native = False  # noqa: SLF001 - the Python backend is the subject

    plain = await counter.count_prompt(
        "gemma4:31b-it-q8_0", [Message(role=MessageRole.USER, content="hello")], []
    )
    odd = await counter.count_prompt(
        "gemma4:31b-it-q8_0", [Message(role=MessageRole.USER, content="hello\U0010ffff")], []
    )
    parts = await counter.count_parts("gemma4:31b-it-q8_0", ["hello", "\U0010ffff"])

    assert plain is not None
    assert odd is None
    assert parts is None


async def test_a_same_tag_replacement_rereads_capacity_and_vocabulary(tmp_path: Path) -> None:
    """A pull under the same tag repoints its manifest at other weights. The
    declared context and the vocabulary are both read again for the new
    weights, together: bounding new weights with the old ones' window is what
    the guard would otherwise do (review on #24, reproduced there by mocking
    the metadata reader: 32768 kept after the weights declared 4096)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, digest="aaa111", context_length=32768)
    counter = GgufTokenCounter(tmp_path)
    assert await counter.native_context_length("primary:latest") == 32768
    before = await counter._vocabulary("primary:latest")  # noqa: SLF001

    write_store(tmp_path, digest="bbb222", context_length=4096)

    assert await counter.native_context_length("primary:latest") == 4096
    after = await counter._vocabulary("primary:latest")  # noqa: SLF001
    assert after is not None and after is not before


async def test_prepare_clears_the_declared_context_too(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, context_length=32768)
    counter = GgufTokenCounter(tmp_path)
    assert await counter.native_context_length("primary:latest") == 32768

    write_store(tmp_path, context_length=8192)  # same manifest, rewritten weights
    await counter.prepare("primary:latest")

    assert await counter.native_context_length("primary:latest") == 8192


async def test_an_unknown_capacity_becomes_known_after_a_same_tag_pull(tmp_path: Path) -> None:
    """A remembered None is a fact about the weights it was read from, not
    about the tag: weights that declare no context, replaced under the same
    tag by weights that do, are read again (review on #31)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, digest="aaa111")
    counter = GgufTokenCounter(tmp_path)
    assert await counter.native_context_length("primary:latest") is None

    write_store(tmp_path, digest="bbb222", context_length=8192)

    assert await counter.native_context_length("primary:latest") == 8192


async def test_a_known_capacity_is_withdrawn_when_the_new_weights_declare_none(
    tmp_path: Path,
) -> None:
    """The opposite direction: the old window must not outlive the weights that
    declared it, even when the new weights declare nothing to replace it with,
    so the guard falls back to the registration rather than a stale figure
    (review on #31)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, digest="aaa111", context_length=32768)
    counter = GgufTokenCounter(tmp_path)
    assert await counter.native_context_length("primary:latest") == 32768

    write_store(tmp_path, digest="bbb222")

    assert await counter.native_context_length("primary:latest") is None


def _replace_after_the_manifest_is_read(
    counter: GgufTokenCounter, store: Path, **replacement: object
) -> None:
    """Repoint the tag once, between the counter's manifest read and its use.

    The interleaving the review on #31 reproduced: a same-tag pull landing after
    the identity was taken and before the weights were read."""
    resolve = counter._resolve  # noqa: SLF001
    fired = False

    def resolve_then_pull(ref: str):  # type: ignore[no-untyped-def]
        nonlocal fired
        snapshot = resolve(ref)
        if not fired:
            fired = True
            write_store(store, **replacement)  # type: ignore[arg-type]
        return snapshot

    counter._resolve = resolve_then_pull  # type: ignore[method-assign]  # noqa: SLF001


def _source(vocabulary: object) -> str:
    """The blob file a vocabulary was built from, on either backend."""
    return Path(getattr(vocabulary, "blob", None) or vocabulary._blob_path).name  # type: ignore[attr-defined]  # noqa: SLF001


async def test_a_pull_between_identity_and_read_cannot_mislabel_the_capacity(
    tmp_path: Path,
) -> None:
    """The window is read from the blob the identified manifest names, so a pull
    in between cannot store the new weights' window under the old identity.
    Rolling the tag back then finds the old window, not the replacement's
    (review on #31: 32768 was returned for a 4096-token model)."""
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, digest="aaa111", context_length=4096)
    counter = GgufTokenCounter(tmp_path)
    _replace_after_the_manifest_is_read(counter, tmp_path, digest="bbb222", context_length=32768)

    assert await counter.native_context_length("primary:latest") == 4096, "A's own window"
    assert await counter.native_context_length("primary:latest") == 32768, "B, once seen"

    write_store(tmp_path, digest="aaa111", context_length=4096)  # rollback

    assert await counter.native_context_length("primary:latest") == 4096


async def test_a_pull_between_identity_and_build_cannot_mislabel_the_vocabulary(
    tmp_path: Path,
) -> None:
    (tmp_path / "blobs").mkdir(parents=True)
    write_store(tmp_path, digest="aaa111")
    counter = GgufTokenCounter(tmp_path)
    _replace_after_the_manifest_is_read(counter, tmp_path, digest="bbb222")

    first = await counter._vocabulary("primary:latest")  # noqa: SLF001
    assert first is not None and _source(first) == "sha256-aaa111"
    second = await counter._vocabulary("primary:latest")  # noqa: SLF001
    assert second is not None and _source(second) == "sha256-bbb222"

    write_store(tmp_path, digest="aaa111")  # rollback

    third = await counter._vocabulary("primary:latest")  # noqa: SLF001
    assert third is not None and _source(third) == "sha256-aaa111"
