"""Cached TokenCounterPort adapter over GGUF metadata."""

from __future__ import annotations

import asyncio
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
    CHAT_TEMPLATE_KEY,
    KNOWN_PRE_TOKENIZERS,
    REQUIRED_KEYS,
    WANTED_KEYS,
)
from .construction import _build_tokenizer, _Vocabulary
from .templates import _build_template

logger = logging.getLogger("app.adapters.tokenizer.gguf_token_counter")


class GgufTokenCounter:
    """`TokenCounterPort` over the GGUF files an Ollama host already holds."""

    def __init__(self, root: Path, *, cache_size: int = 2) -> None:
        self._root = root
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, _Vocabulary | None] = OrderedDict()
        self._lock = asyncio.Lock()
        """One lock for all references, not one per reference.

        Building is rare — once per model per process — and costs a quarter of
        a second, so the contention this could cause is a quarter-second wait
        on the first request to a second model. What it prevents is worth more:
        without it, a burst of requests arriving at a cold process each start
        their own build of the same 132 MB tokeniser.
        """

    async def prepare(self, ref: str) -> bool:
        """Build now, and reconsider a reference this host could not resolve.

        The forgetting is the point of `prepare` being separate from a count.
        A model can be pulled after the first request that asked for it, and a
        mount can arrive at the next deploy; the negative cache below would
        otherwise hold "no vocabulary" for the life of the process. Loading a
        model is exactly the moment that changes, and it is the moment this is
        called from.
        """
        async with self._lock:
            self._cache.pop(ref, None)
        return await self._vocabulary(ref) is not None

    async def count_prompt(
        self, ref: str, messages: Sequence[Message], tools: Sequence[ToolDefinition]
    ) -> int | None:
        vocabulary = await self._vocabulary(ref)
        if vocabulary is None or not vocabulary.has_template:
            return None
        try:
            payload = [message_payload(m) for m in messages]
        except RuntimeCapabilityError:
            # The adapter refuses a tool call whose arguments are not JSON, and
            # this is the same conversion, so the same refusal would arrive a
            # few lines later from the place that owns it. Declining to count
            # is the honest answer here: the request is measured by the
            # estimate, and then refused by the adapter for its real reason.
            return None
        try:
            return await asyncio.to_thread(vocabulary.count_prompt, payload, tool_payload(tools))
        except Exception as exc:  # noqa: BLE001
            # Templates refuse payload shapes: this one raises for a
            # conversation with no user turn, and for a system message that is
            # not first. That is a statement about the template's assumptions,
            # not about the request — Ollama renders the same conversation with
            # its own renderer and answers it — so the count falls back rather
            # than the request failing.
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
        parts = tuple(texts)
        return await asyncio.to_thread(lambda: [vocabulary.encode(text) for text in parts])

    async def _vocabulary(self, ref: str) -> _Vocabulary | None:
        cached = self._cache.get(ref, ...)
        if cached is not ...:
            # A failed build is cached as `None` and not retried. The failures
            # are all durable — no mount, no manifest, an unrecognised
            # pre-tokeniser — and retrying means reading a header of tens of
            # megabytes on every request to a model that will never have one.
            # `prepare` is what clears it, and loading a model calls that.
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
        """Read one GGUF header and build from it, or say why not.

        Every failure is logged once and answered with `None`, because the
        caller's response to all of them is the same. Logged at INFO rather
        than WARNING for a reference this host holds no weights for — an MLX
        model reaching here is ordinary, not a fault — and at WARNING when the
        file is present and unusable, which is the case an operator can fix.
        """
        try:
            blob = weights_path(self._root, ref)
        except (BlobNotFound, InvalidModelReferenceError) as exc:
            logger.info("no vocabulary for %s, counting by estimate instead: %s", ref, exc)
            return None
        try:
            metadata = read_metadata(
                blob, lambda key: key in WANTED_KEYS or key == CHAT_TEMPLATE_KEY
            )
        # `Exception`, not the two named classes alone. Reading a file the
        # platform does not own is exactly where an unanticipated failure
        # belongs, and the cost of letting one through is not a bad count but a
        # 500 on every request routed to that model — with the header re-read
        # each time, because a build that raises caches nothing. The reader now
        # raises `GgufError` for every malformation it knows of; this is the
        # backstop for the ones it does not.
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not read the vocabulary out of %s for %s: %s", blob.name, ref, exc
            )
            return None

        missing = [key for key in REQUIRED_KEYS if key not in metadata]
        if missing:
            logger.warning("%s carries no %s; counting %s by estimate", blob.name, missing, ref)
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
        if family != BPE_MODEL:
            logger.warning(
                "%s declares the %r tokeniser model rather than %r; counting %s by estimate",
                blob.name,
                family,
                BPE_MODEL,
                ref,
            )
            return None
        try:
            tokenizer = _build_tokenizer(metadata)
            source = metadata.get(CHAT_TEMPLATE_KEY)
            template = _build_template(source) if isinstance(source, str) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not build a tokeniser for %s from %s: %s", ref, blob.name, exc)
            return None
        if template is None:
            logger.warning(
                "%s carries no chat template, so the framing the runtime adds cannot be "
                "counted for %s; counting it by estimate instead",
                blob.name,
                ref,
            )
            return None
        logger.info(
            "counting %s with its own vocabulary: %s entries from %s, pre-tokeniser %r",
            ref,
            len(metadata["tokenizer.ggml.tokens"]),
            blob.name,
            scheme,
        )
        return _Vocabulary(ref=ref, blob=blob.name, tokenizer=tokenizer, template=template)
