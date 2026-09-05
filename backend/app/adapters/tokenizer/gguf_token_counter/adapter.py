"""Cached TokenCounterPort adapter over GGUF metadata."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path

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

_CHATML_FALLBACK = (
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


class GgufTokenCounter:
    """`TokenCounterPort` over the GGUF files an Ollama host already holds."""

    def __init__(self, root: Path, *, cache_size: int = 2) -> None:
        self._root = root
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, _Vocabulary | None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._use_native = _HAS_NATIVE
        self._native_prefix = str(root) + ":"
        self._native_negative: set[str] = set()
        if self._use_native:
            logger.info("nexus_native available; using Rust tokenizer backend")

    def _resolve_blob(self, ref: str) -> str | None:
        """Resolve a model ref to its GGUF blob path, or None."""
        try:
            return str(weights_path(self._root, ref))
        except (BlobNotFound, InvalidModelReferenceError) as exc:
            logger.info("no vocabulary for %s, counting by estimate instead: %s", ref, exc)
            return None

    def _native_key(self, ref: str) -> str:
        return self._native_prefix + ref

    async def prepare(self, ref: str) -> bool:
        if self._use_native:
            self._native_negative.discard(ref)
            blob_path = self._resolve_blob(ref)
            if blob_path is None:
                self._native_negative.add(ref)
                return False
            key = self._native_key(ref)
            result: tuple[bool, str | None] = await asyncio.to_thread(
                _nexus_native.prepare, blob_path, key
            )
            success, error = result
            if not success:
                logger.warning("could not build a native tokeniser for %s: %s", ref, error)
                self._native_negative.add(ref)
            else:
                logger.info("counting %s with Rust tokenizer backend", ref)
            return success

        async with self._lock:
            self._cache.pop(ref, None)
        return await self._vocabulary(ref) is not None

    async def count_prompt(
        self, ref: str, messages: Sequence[Message], tools: Sequence[ToolDefinition]
    ) -> int | None:
        if self._use_native:
            if ref in self._native_negative:
                return None
            blob_path = self._resolve_blob(ref)
            if blob_path is None:
                return None
            try:
                payload = [message_payload(m) for m in messages]
            except RuntimeCapabilityError:
                return None
            key = self._native_key(ref)
            messages_json = json.dumps(payload, ensure_ascii=False)
            tools_json = json.dumps(tool_payload(tools), ensure_ascii=False)
            try:
                return await asyncio.to_thread(
                    _nexus_native.count_prompt, blob_path, key, messages_json, tools_json
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "native count_prompt failed for %s, falling back to estimate: %s", ref, exc
                )
                return None

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
        if self._use_native:
            if ref in self._native_negative:
                return None
            blob_path = self._resolve_blob(ref)
            if blob_path is None:
                return None
            key = self._native_key(ref)
            try:
                return await asyncio.to_thread(
                    _nexus_native.count_parts, blob_path, key, list(texts)
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "native count_parts failed for %s, falling back to estimate: %s", ref, exc
                )
                return None

        vocabulary = await self._vocabulary(ref)
        if vocabulary is None:
            return None
        parts = tuple(texts)
        return await asyncio.to_thread(lambda: [vocabulary.encode(text) for text in parts])

    # --- Python-only fallback path below (unchanged) ---

    async def _vocabulary(self, ref: str) -> _Vocabulary | None:
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

    def _build(self, ref: str) -> _Vocabulary | None:
        try:
            blob = weights_path(self._root, ref)
        except (BlobNotFound, InvalidModelReferenceError) as exc:
            logger.info("no vocabulary for %s, counting by estimate instead: %s", ref, exc)
            return None
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
