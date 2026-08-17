"""Exact prompt tokens, from the vocabulary and chat template of one GGUF.

What this counts is the string the runtime will build, not the text the caller
sent: the model's own chat template is rendered over the same payload the
Ollama adapter serialises, and the result is encoded with the model's own
vocabulary. Both artefacts come out of the file `ref` resolves to, so there is
no version of this that can describe a different model than the one that will
answer.

**Measured against `prompt_eval_count` on the live runtime, 2026-08-17.** With
`raw: true`, which applies no template, the counts are equal on every content
type this platform has measured — function-tool JSON, TypeScript, Python,
English prose, a Chinese runbook and a uuid list, on both `qwen2.5:7b` and
`qwen3.6:35b-a3b-q8_0`, six for six exactly. Through `/api/chat`, which applies
the template, what is left is a constant:

| payload                      | counted - actual |
|------------------------------|------------------|
| one user turn                | +2               |
| system and user              | +2               |
| five alternating turns       | +2               |
| a tool call and its result   | +14              |
| 12 tool definitions          | +12              |
| 60 tool definitions          | +12              |

The constant does not grow with the payload — 12 definitions and 60 cost the
same +12 — so at the 122880 ceiling this is exact to within about one part in
ten thousand, and the sign is the safe one: the count is never below what the
runtime charges. Two of those tokens are a `<think>` opener the template emits
and Ollama does not, and the rest is a slightly shorter tool preamble in
Ollama's own renderer. Neither is worth a correction constant, which is the
kind of thing this file exists to remove.

**The residual is measured continuously, not trusted.** `_log_estimate_drift`
in `RouteChatRequest` compares whatever counted a request against the
`prompt_eval_count` the runtime reports for it, so a runtime upgrade that
changes the framing shows up as a line in the log rather than as a ceiling that
quietly stopped describing the hardware.

**Cost, measured on the Mac Studio.** Reading the 11.9 MiB metadata header of
`qwen3.6:35b-a3b-q8_0` takes 0.14 s and building the tokeniser 0.13 s, both
once per reference; the tokeniser then holds 132 MB for a 248320-entry
vocabulary, and a second one costs about 25 MB more. Encoding is 2.7 ms for
20 KB and 50 ms for 300 KB, which is why every encode goes to a worker thread:
50 ms on the event loop is 50 ms of every other stream on this process
stopping.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.adapters.runtime.ollama_adapter import message_payload, tool_payload
from app.adapters.tokenizer.gguf import iter_merges, read_metadata
from app.adapters.tokenizer.ollama_blobs import BlobNotFound, weights_path
from app.domain.entities.chat import Message, ToolDefinition
from app.domain.exceptions import InvalidModelReferenceError, RuntimeCapabilityError

logger = logging.getLogger(__name__)

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
"""The Rust library parallelises `encode_batch` and warns after a fork if it is
left to decide for itself. Every call here encodes one string on a worker
thread of a process that already has an event loop to keep responsive, so the
parallelism is not wanted and the warning is not informative."""

WANTED_KEYS = (
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.token_type",
    "tokenizer.ggml.pre",
    "tokenizer.ggml.model",
)
REQUIRED_KEYS = ("tokenizer.ggml.tokens", "tokenizer.ggml.merges")
CHAT_TEMPLATE_KEY = "tokenizer.chat_template"
BPE_MODEL = "gpt2"
CONTROL_TOKEN_TYPE = 3

PRE_TOKENIZER_PATTERN = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+|\s+(?!\S)|\s+"
)
"""How the text is split before merges are applied.

This is the one thing not read out of the GGUF, because the format does not
carry it: `tokenizer.ggml.pre` names a *scheme* (`qwen2`, `qwen35`) whose
regular expression lives in the runtime's source rather than in the file. The
pattern above is the one both schemes this deployment serves use, and the
evidence that it is right is the six-for-six agreement with `prompt_eval_count`
recorded in the module docstring — a wrong split still round-trips, so equality
with the runtime is the only check that means anything.

A model declaring a third scheme is refused by `KNOWN_PRE_TOKENIZERS` below
rather than counted with this pattern, because a wrong split is the one failure
here that nothing downstream would notice.
"""

KNOWN_PRE_TOKENIZERS = frozenset({"qwen2", "qwen35"})
"""The schemes the pattern above has been checked against on real payloads.

A model declaring anything else falls back to the character estimate, and this
list is how a third scheme becomes somebody's decision instead of a silent
approximation. Refusing to guess costs the exactness this whole file exists
for, and it is still the right trade: the estimate is wrong by factors this
repository has measured and published, while a vocabulary that splits text the
wrong way is wrong by an amount no instrument here would report — the drift log
would show it, and read as a runtime change rather than as a bad guess.

Adding a scheme means measuring it, not recognising the name: send payloads of
each content type through `/api/generate` with `raw: true` and compare
`prompt_eval_count` against this tokeniser, as was done for both entries here.
"""


class _Vocabulary:
    """One model's tokeniser and chat template, built once and shared.

    Both objects are used from worker threads and neither is mutated after
    construction: `Tokenizer.encode` and `Template.render` each take only a
    shared reference, so no lock is needed around the counting itself. The lock
    in the counter guards *building*, which is a different problem.
    """

    __slots__ = ("_template", "_tokenizer", "blob", "ref")

    def __init__(self, ref: str, blob: str, tokenizer: Any, template: Any) -> None:
        self.ref = ref
        self.blob = blob
        self._tokenizer = tokenizer
        self._template = template

    @property
    def has_template(self) -> bool:
        return self._template is not None

    def encode(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def count_prompt(self, messages: Sequence[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
        rendered = self._template.render(
            messages=list(messages),
            tools=tools or None,
            add_generation_prompt=True,
        )
        return self.encode(rendered)


def _build_tokenizer(metadata: dict[str, Any]) -> Any:
    from tokenizers import AddedToken, Regex, Tokenizer, decoders, pre_tokenizers
    from tokenizers.models import BPE

    tokens: list[str] = metadata["tokenizer.ggml.tokens"]
    merges: list[str] = metadata["tokenizer.ggml.merges"]
    types: list[int] = metadata.get("tokenizer.ggml.token_type") or []
    tokenizer = Tokenizer(
        BPE(
            vocab={token: index for index, token in enumerate(tokens)},
            merges=list(iter_merges(merges)),
            fuse_unk=False,
            byte_fallback=False,
        )
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence(
        [
            pre_tokenizers.Split(Regex(PRE_TOKENIZER_PATTERN), behavior="isolated", invert=False),
            # `use_regex=False` because the split above already did that job.
            # Left at its default, ByteLevel applies GPT-2's own pattern on top
            # of this model's, and the two disagree about digits.
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ]
    )
    tokenizer.decoder = decoders.ByteLevel()
    # Control tokens are added as special ones so `<|im_start|>` costs the one
    # token the runtime charges for it rather than the eight its spelling would
    # otherwise be merged into. The template emits them; nothing a caller sends
    # reaches this as a special token, because `add_special_tokens=False` is
    # passed on every encode.
    special = [
        AddedToken(token, special=True, normalized=False)
        for token, kind in zip(tokens, types, strict=False)
        if kind == CONTROL_TOKEN_TYPE
    ]
    if special:
        tokenizer.add_special_tokens(special)
    return tokenizer


def _build_template(source: str) -> Any:
    """The model's own chat template, rendered in a sandbox with Ollama's
    spelling of `tojson`.

    **The sandbox is not about the template**, which ships inside the weights an
    operator registered and is as trusted as they are. It is about what is
    rendered *through* it: message content is caller text, and a sandboxed
    environment is the difference between a template bug and a template bug that
    can reach an attribute of a Python object.

    **`tojson` is overridden because Jinja's own sorts keys**, and that showed
    up as a real error rather than a stylistic one: with sorted keys the count
    drifted by one token per tool definition — 12 low on 12 definitions, 58 low
    on 60 — so a 286-definition client would have been under-counted by about
    300 tokens, in the direction that ends in a silent truncation. Serialised in
    insertion order the same payloads are a constant +12 regardless of how many
    definitions there are.
    """
    from jinja2.exceptions import TemplateError
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def _raise(message: str) -> Any:
        raise TemplateError(message)

    environment = ImmutableSandboxedEnvironment(keep_trailing_newline=True)
    environment.globals["raise_exception"] = _raise
    # A plain string, not `Markup`: this environment does not escape, because
    # what it renders is counted and never served, so marking the JSON safe
    # would only be a claim about HTML that nothing here makes.
    environment.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
    return environment.from_string(source)


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
