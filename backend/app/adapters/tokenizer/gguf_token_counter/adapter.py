"""Cached TokenCounterPort adapter over GGUF metadata.

When nexus_native is available, the adapter uses Rust for GGUF header
parsing, tokenizer construction and token encoding (the CPU-bound parts),
while keeping template rendering in Python Jinja2 (which handles every
chat template including those using `namespace()` and `macro`).
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.adapters.runtime.ollama_adapter import message_payload, tool_payload
from app.adapters.tokenizer.gguf import read_metadata
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from app.domain.entities.chat import Message, ToolDefinition
from app.domain.exceptions import InvalidModelReferenceError, RuntimeCapabilityError

from .constants import (
    BPE_MODEL,
    BPE_REQUIRED_KEYS,
    CHAT_TEMPLATE_KEY,
    KNOWN_MODELS,
    KNOWN_PRE_TOKENIZERS,
    UNIGRAM_REQUIRED_KEYS,
    WANTED_KEYS,
)
from .construction import _Vocabulary, build_tokenizer_for_model
from .templates import _build_template

logger = logging.getLogger("app.adapters.tokenizer.gguf_token_counter")

_NATIVE_CONTEXT_CACHE = 64
"""How many declared context lengths one process remembers.

Not `token_counter_cache_size`, which bounds 132 MB vocabularies against the
memory budget. These are integers, and the thing that fills them is a register
form being typed into one character at a time.
"""


_CHATML_FALLBACK = (
    # Tools first, and this block is not decoration. A model with no chat
    # template in its GGUF falls back to this one, and until 2026-09-07 it
    # iterated `messages` alone — so on `gemma4:31b-it-q8_0`, which carries a
    # template of zero characters and serves `chat` and `code`, every tool
    # definition was counted as nothing at all. Measured that day by holding a
    # message fixed and varying the tool count: 29 tokens for none, 29 for
    # twelve, 29 for thirty-six, against `qwen2.5:7b`'s 57 / 1,395 / 3,915.
    #
    # That is the direction this port's own docstring warns about — an
    # under-count "is what precedes a prompt the runtime truncates in silence"
    # — and it reached `max_context_length`, the per-model truncation guard,
    # `_warn_if_tools_dominate`, and Tier 0 compaction, which exists to trim
    # tool definitions and found none to trim.
    #
    # Name, description and parameter schema, because that is what a runtime
    # actually puts in front of a model for a tool, and because it measures
    # closest: against the runtime's own `prompt_eval_count` for a twelve-tool
    # agent payload, this reads 6,748 where the runtime read 6,607 and the
    # tool-less fallback read 5,723. Rendering the whole OpenAI-shaped object
    # instead reaches 6,977. **Over by 2%, which is the safe direction**: this
    # figure decides whether a prompt is refused, so erring high refuses a
    # request that would have fitted, while erring low serves one the runtime
    # then cuts without saying so.
    "{% if tools %}<|im_start|>system\n"
    "{% for t in tools %}"
    "{{ t.function.name }}: {{ t.function.description }}\n"
    "{{ t.function.parameters | tojson }}\n"
    "{% endfor %}"
    "<|im_end|>\n{% endif %}"
    "{% for message in messages %}"
    "<|im_start|>{{ message.role }}\n{{ message.content }}<|im_end|>\n"
    "{% endfor %}"
    "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
)

try:
    import nexus_native as _nexus_native

    _HAS_NATIVE = True
except ImportError:
    _nexus_native = None
    _HAS_NATIVE = False


class _NativeVocabulary:
    """Wraps a Rust-side tokenizer with a Python-side Jinja2 template."""

    __slots__ = ("_blob_path", "_cache_key", "_template")

    def __init__(self, blob_path: str, cache_key: str, template: Any) -> None:
        self._blob_path = blob_path
        self._cache_key = cache_key
        self._template = template

    @property
    def has_template(self) -> bool:
        return self._template is not None

    def encode(self, text: str) -> int:
        result: int | None = _nexus_native.encode_text(self._blob_path, self._cache_key, text)
        if result is None:
            return 0
        return result

    def count_prompt(
        self, messages: Sequence[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> int | None:
        rendered = self._template.render(
            messages=list(messages),
            tools=tools or None,
            add_generation_prompt=True,
        )
        result: int | None = _nexus_native.encode_text(self._blob_path, self._cache_key, rendered)
        return result

    def count_parts(self, texts: Sequence[str]) -> Sequence[int] | None:
        result: list[int] | None = _nexus_native.encode_texts(
            self._blob_path, self._cache_key, list(texts)
        )
        return result


class GgufTokenCounter:
    """`TokenCounterPort` over the GGUF files an Ollama host already holds."""

    def __init__(self, root: Path, *, cache_size: int = 2) -> None:
        self._root = root
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, _Vocabulary | _NativeVocabulary | None] = OrderedDict()
        self._native_context: OrderedDict[str, int | None] = OrderedDict()
        """Declared context lengths, bounded separately from the vocabularies.

        Sharing `cache_size` with them was wrong and the review that caught it
        reasoned from the consequence: `/admin/model-reference` is typed into,
        so a register form walks this cache through every prefix of a reference
        — `gem`, `gemm`, `gemma` — and at two entries the real models' figures
        were evicted before the operator finished the word.

        The two caches are bounded for different reasons. A vocabulary is 132 MB
        resident and its ceiling is the memory budget this whole deployment is
        designed around. An entry here is an integer or None. `_NATIVE_CONTEXT_CACHE`
        is therefore sized for the misses a form produces rather than for
        memory, which is what a cache of integers should be sized for.
        """
        self._lock = asyncio.Lock()
        self._use_native = _HAS_NATIVE
        if self._use_native:
            logger.info("nexus_native available; using Rust tokenizer backend")

    async def prepare(self, ref: str) -> bool:
        async with self._lock:
            self._cache.pop(ref, None)
        return await self._vocabulary(ref) is not None

    async def native_context_length(self, ref: str) -> int | None:
        """The `<family>.context_length` the GGUF header declares.

        A separate read from the vocabulary and a separate cache, because the
        two are wanted at different moments: the vocabulary on every request
        that counts a prompt, this one when a caller is deciding how much
        context to ask the runtime to size a runner for. Reading it does not
        build a tokenizer, so it costs a header scan that skips every value it
        is not asked for.

        The family prefix is not hardcoded — `qwen2.context_length`,
        `gemma4.context_length`, and one per architecture — so the key is
        matched by its suffix. A header carrying two would be a file this
        reader has no opinion about; the smallest is taken, because the purpose
        of this number is to bound something.
        """
        async with self._lock:
            if ref in self._native_context:
                self._native_context.move_to_end(ref)
                return self._native_context[ref]
        value = await asyncio.to_thread(self._read_native_context, ref)
        async with self._lock:
            self._native_context[ref] = value
            self._native_context.move_to_end(ref)
            while len(self._native_context) > _NATIVE_CONTEXT_CACHE:
                self._native_context.popitem(last=False)
        return value

    def _read_native_context(self, ref: str) -> int | None:
        try:
            blob = weights_path(self._root, ref)
        except (BlobNotFound, InvalidModelReferenceError) as exc:
            logger.info("no GGUF for %s, cannot read its declared context: %s", ref, exc)
            return None
        try:
            metadata = read_metadata(blob, lambda key: key.endswith(".context_length"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read the declared context out of %s: %s", blob.name, exc)
            return None
        values = [int(v) for v in metadata.values() if isinstance(v, int) and v > 0]
        if not values:
            logger.info("%s declares no context length", blob.name)
            return None
        return min(values)

    async def count_prompt(
        self, ref: str, messages: Sequence[Message], tools: Sequence[ToolDefinition]
    ) -> int | None:
        vocabulary = await self._vocabulary(ref)
        if vocabulary is None or not vocabulary.has_template:
            return None
        try:
            payload = [message_payload(m) for m in messages]
        except RuntimeCapabilityError:
            return None
        try:
            return await asyncio.to_thread(vocabulary.count_prompt, payload, tool_payload(tools))
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "could not count %s with its own template, falling back to the estimate: %s",
                ref,
                exc,
            )
            return None

    async def count_parts(self, ref: str, texts: Sequence[str]) -> Sequence[int] | None:
        vocabulary = await self._vocabulary(ref)
        if vocabulary is None:
            return None
        if isinstance(vocabulary, _NativeVocabulary):
            try:
                return await asyncio.to_thread(vocabulary.count_parts, texts)
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "native count_parts failed for %s, falling back to estimate: %s", ref, exc
                )
                return None
        parts = tuple(texts)
        return await asyncio.to_thread(lambda: [vocabulary.encode(text) for text in parts])

    async def _vocabulary(self, ref: str) -> _Vocabulary | _NativeVocabulary | None:
        cached = self._cache.get(ref, ...)
        if cached is not ...:
            self._cache.move_to_end(ref)
            return cached
        async with self._lock:
            if ref in self._cache:
                return self._cache[ref]
            built = await asyncio.to_thread(self._build, ref)
            self._cache[ref] = built
            self._cache.move_to_end(ref)
            while len(self._cache) > self._cache_size:
                evicted, _ = self._cache.popitem(last=False)
                logger.info(
                    "dropped the cached vocabulary for %s to stay within the cache", evicted
                )
            return built

    def _build(self, ref: str) -> _Vocabulary | _NativeVocabulary | None:
        try:
            blob = weights_path(self._root, ref)
        except (BlobNotFound, InvalidModelReferenceError) as exc:
            logger.info("no vocabulary for %s, counting by estimate instead: %s", ref, exc)
            return None

        if self._use_native:
            return self._build_native(ref, blob)
        return self._build_python(ref, blob)

    def _build_native(self, ref: str, blob: Path) -> _NativeVocabulary | _Vocabulary | None:
        """Build the tokenizer directly in Rust from the GGUF blob.

        Template rendering stays in Python Jinja2 (which handles ``namespace()``,
        ``macro`` and every other template the deployment has seen), so the GGUF
        is still read on the Python side for the chat template.  If the Rust
        build fails, the full Python tokenizer is returned instead of ``None``
        so the model still gets real token counts rather than the character
        estimate.
        """
        python_vocab = self._build_python(ref, blob)
        if python_vocab is None:
            return None

        cache_key = str(blob) + ":" + ref
        result: tuple[bool, str | None] = _nexus_native.prepare(str(blob), cache_key)
        success, error = result
        if not success:
            logger.warning(
                "Rust tokenizer build failed for %s: %s; falling back to Python tokenizer",
                ref,
                error,
            )
            return python_vocab

        logger.info("counting %s with Rust encoder + Python template from %s", ref, blob.name)
        return _NativeVocabulary(
            blob_path=str(blob), cache_key=cache_key, template=python_vocab._template
        )

    def _build_python(self, ref: str, blob: Path) -> _Vocabulary | None:
        try:
            metadata = read_metadata(
                blob, lambda key: key in WANTED_KEYS or key == CHAT_TEMPLATE_KEY
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not read the vocabulary out of %s for %s: %s", blob.name, ref, exc
            )
            return None

        scheme = str(metadata.get("tokenizer.ggml.pre", ""))
        if scheme not in KNOWN_PRE_TOKENIZERS:
            logger.warning(
                "%s declares the %r pre-tokeniser, which has not been measured against this "
                "platform's pattern; counting %s by estimate instead",
                blob.name,
                scheme,
                ref,
            )
            return None
        family = str(metadata.get("tokenizer.ggml.model", ""))
        if family not in KNOWN_MODELS:
            logger.warning(
                "%s declares the %r tokeniser model, which is not one of %s; "
                "counting %s by estimate",
                blob.name,
                family,
                ", ".join(sorted(KNOWN_MODELS)),
                ref,
            )
            return None
        required = BPE_REQUIRED_KEYS if family == BPE_MODEL else UNIGRAM_REQUIRED_KEYS
        missing = [key for key in required if key not in metadata]
        if missing:
            logger.warning("%s carries no %s; counting %s by estimate", blob.name, missing, ref)
            return None
        try:
            tokenizer = build_tokenizer_for_model(metadata)
            source = metadata.get(CHAT_TEMPLATE_KEY)
            if not isinstance(source, str):
                source = _CHATML_FALLBACK
            template = _build_template(source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not build a tokeniser for %s from %s: %s", ref, blob.name, exc)
            return None
        logger.info(
            "counting %s with its own vocabulary: %s entries from %s, pre-tokeniser %r",
            ref,
            len(metadata["tokenizer.ggml.tokens"]),
            blob.name,
            scheme,
        )
        return _Vocabulary(ref=ref, blob=blob.name, tokenizer=tokenizer, template=template)
