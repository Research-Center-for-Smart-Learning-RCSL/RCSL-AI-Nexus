"""Ollama runtime adapter.

Talks to an Ollama running natively on the macOS host, reached through
`host.docker.internal`, because containers on macOS cannot use the GPU. See
docs/ARCHITECTURE.md section 0.1.

Everything goes over the HTTP API. Nothing here builds a shell command, and
every reference passes `parse_model_ref` first.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.validation import assert_valid_model_ref
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import PullProgress, RuntimeResidency
from app.domain.exceptions import DomainError, ModelNotFoundError, NoAvailableModelError

logger = logging.getLogger(__name__)

DEFAULT_KEEP_ALIVE = "-1"
"""Keep a loaded model resident until something asks otherwise.

The registry already models residency: a row is `loaded`, the memory budget
reserves its weights, and `unload` releases it. Leaving Ollama's own five-minute
timer in charge lets a component with none of that information overrule all
three, and it did — the model was reloaded 14 times in one day, and `load`'s own
`10m` never took effect once, because `generate` sent no `keep_alive` and every
generation reset the timer to the server default."""


def _keep_alive(raw: str) -> str | int:
    """Ollama takes a duration string (`10m`) or a number of seconds, where a
    negative number means forever — but the *string* `"-1"` is refused with
    `time: missing unit in duration "-1"`, so a numeric setting has to be sent
    as a number rather than as the text the environment supplied.

    Worth the conversion rather than a documented footgun: the rejection is a
    400, which `_raise_for_status` maps to `NoAvailableModelError`, so a caller
    would see "No model is currently available" and go looking at routing
    policies. Verified against Ollama 0.32.4."""
    try:
        return int(raw.strip())
    except ValueError:
        return raw


# Ollama's done_reason vocabulary is its own. OpenAI clients branch on
# finish_reason, and an unrecognised value ("load", "unload") reads to them as
# a protocol error, so anything outside the known set is reported as "stop".
_FINISH_REASONS = {"stop": "stop", "length": "length", "load": "stop", "unload": "stop"}


def _finish_reason(done_reason: str | None) -> str:
    return _FINISH_REASONS.get(done_reason or "stop", "stop")


def _spellings(name: str) -> tuple[str, ...]:
    """Every reference Ollama would answer to for a reported model name.

    Ollama canonicalises a bare `nomic-embed-text` to `nomic-embed-text:latest`
    in its own listings, while the registry may hold either spelling. The tag
    lives after the last `/`, so `namespace/name` stays intact."""
    _, _, tail = name.rpartition("/")
    if tail.endswith(":latest"):
        return (name, name[: -len(":latest")])
    return (name,)


class OllamaAdapter:
    def __init__(
        self,
        base_url: str,
        request_timeout_seconds: int = 300,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._keep_alive = _keep_alive(keep_alive)
        # Generation legitimately takes minutes, so the read timeout is long,
        # but a host that is simply not there must fail fast rather than
        # holding a concurrency slot for the full request timeout.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(request_timeout_seconds), write=30.0, pool=5.0
        )

    # --- inference -------------------------------------------------------

    def validate_ref(self, ref: str) -> None:
        """Ollama's grammar, exposed so the registry can refuse a reference at
        the moment someone types it rather than at the first download."""
        assert_valid_model_ref(ref)

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream a completion.

        An async generator, so it is declared without `async def` in the port
        and called without await. The `finally` inside the `async with` is
        what closes the upstream request when a client disconnects; without
        it Ollama keeps generating for someone who has already gone.
        """
        assert_valid_model_ref(ref)
        payload: dict[str, Any] = {
            "model": ref,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": True,
        }
        if max_tokens is not None:
            # Stopping at the source beats counting chunks and cutting the
            # stream: the model stops generating rather than producing tokens
            # nobody reads.
            payload["options"] = {"num_predict": max_tokens}
        # Sent on generation as well as on load. Ollama applies its own default
        # to any request that omits it, so a generate without this silently
        # overwrites whatever `load` asked for — which is how a 10-minute
        # setting became a 5-minute one nobody had chosen.
        payload["keep_alive"] = self._keep_alive
        if not thinking:
            # Only ever sent as `false`. Ollama refuses `think: true` for a
            # model that does not support it — `"qwen2.5:7b" does not support
            # thinking` — so a registry holding both kinds cannot ask for
            # thinking at all. `True` here therefore means "send nothing and
            # let the model do what it does", not "ask it to think". That
            # asymmetry is what makes it safe for a caller to send `think: true`
            # over the wire: it never reaches the runtime as a demand.
            #
            # The other direction was checked rather than assumed, because the
            # asymmetry above gives no reason to expect it: `think: false`
            # against `qwen2.5:7b`, which has no thinking capability, returns a
            # normal completion rather than the error `true` earns. So a request
            # that suppresses thinking is safe whichever model routing picks,
            # including the non-thinking fallback.
            #
            # Graded values are not offered because they do not work: Ollama
            # accepts `think: "low"` for this model without error and the
            # behaviour is identical to the default — measured at 8192 tokens,
            # same token count, same 228s, same empty answer.
            payload["think"] = False

        counted = 0
        saw_done = False
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("ollama emitted a non-JSON line, ignoring")
                        continue

                    if event.get("error"):
                        raise NoAvailableModelError(detail=f"ollama: {event['error']}")

                    message = event.get("message") or {}
                    delta = message.get("content") or ""
                    # A thinking model puts its deliberation here and leaves
                    # `content` empty until it is finished, which for a hard
                    # question can be the whole generation. Dropping this field
                    # made the adapter produce nothing at all for 93 seconds on
                    # a question that used its entire token budget thinking.
                    reasoning = message.get("thinking") or ""

                    if event.get("done"):
                        saw_done = True
                        # Ollama reports the authoritative token count only at
                        # the end. Chunks were counted as one apiece so that a
                        # disconnect still bills something sensible, so emit
                        # the difference here rather than the whole figure,
                        # which would otherwise be counted twice.
                        eval_count = int(event.get("eval_count") or 0)
                        correction = eval_count - counted
                        if correction < 0:
                            # Chunks outnumbered the model's own token count.
                            # There is no downward correction to make, so this
                            # is logged rather than silently over-billed.
                            logger.info(
                                "ollama eval_count=%s below chunk count=%s for %s",
                                eval_count,
                                counted,
                                ref,
                            )
                            correction = 0
                        yield CompletionChunk(
                            delta=delta,
                            reasoning=reasoning,
                            finish_reason=_finish_reason(event.get("done_reason")),
                            token_count=correction,
                            # Reported once, here, for the whole request.
                            # Ollama has always sent it; nothing read it until
                            # 2026-08-04, so every prompt was free of quota.
                            prompt_tokens=int(event.get("prompt_eval_count") or 0),
                        )
                        return

                    if delta or reasoning:
                        # Reasoning counts. Ollama's `eval_count` includes the
                        # thinking tokens, so excluding them here would make the
                        # end-of-stream correction re-bill every one of them.
                        counted += 1
                        yield CompletionChunk(delta=delta, reasoning=reasoning, token_count=1)

                if not saw_done:
                    # The stream ended without a terminal event: the model was
                    # evicted, Ollama restarted, or the read timeout fired.
                    # Returning quietly would let the caller record a complete
                    # generation and report "stop" to the client.
                    raise NoAvailableModelError(
                        detail=f"ollama stream for {ref} ended without a done event"
                    )

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for a batch, through Ollama's `/api/embed`.

        The batching endpoint, not the older single-input `/api/embeddings`:
        one round trip per passage would dominate the cost of indexing a
        document. The response's `embeddings` is a list per input, in order.
        """
        assert_valid_model_ref(ref)
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post("/api/embed", json={"model": ref, "input": list(texts)})
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(
                    detail=f"ollama /api/embed returned {response.status_code}"
                )

        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list):
            # A model that is not an embedding model answers 200 with no
            # `embeddings` key. Refusing here is what stops that becoming a
            # knowledge base indexed with nothing.
            raise NoAvailableModelError(detail=f"ollama returned no embeddings for {ref}")
        return [[float(value) for value in vector] for vector in embeddings]

    # --- model lifecycle -------------------------------------------------

    async def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """Stream download progress.

        Also an async generator: Ollama's pull endpoint answers with a stream
        of NDJSON progress objects, so a plain POST would report no progress
        and give no reliable completion signal.
        """
        assert_valid_model_ref(ref)

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream(
                "POST", "/api/pull", json={"model": ref, "stream": True}
            ) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("error"):
                        raise DomainError(detail=f"ollama pull failed: {event['error']}")

                    yield PullProgress(
                        status=event.get("status", ""),
                        completed_bytes=event.get("completed"),
                        total_bytes=event.get("total"),
                    )

    async def load(self, ref: str) -> None:
        """Warm a model into memory.

        An empty prompt with a keep_alive is Ollama's documented way to load
        without generating anything — but an embedding model refuses
        `/api/generate` outright (400, `"does not support generate"`), so that
        refusal is answered by warming through `/api/embed` with an empty
        input, which loads the weights and honours `keep_alive` the same way.
        Verified against Ollama on the Mac Studio: both directions, load and
        evict, behave identically to the generate path.
        """
        assert_valid_model_ref(ref)
        await self._post_lifecycle(ref, keep_alive=self._keep_alive)

    async def unload(self, ref: str) -> None:
        """Evict immediately. `keep_alive: 0` is the documented signal."""
        assert_valid_model_ref(ref)
        await self._post_lifecycle(ref, keep_alive=0)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(5.0)
            ) as client:
                response = await client.get("/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def residency(self) -> RuntimeResidency | None:
        """What Ollama is actually holding: `/api/ps` for resident models,
        `/api/tags` for what is on disk.

        Returns None when either call fails, because "could not ask" and
        "asked, and nothing is loaded" must not read the same: an unreachable
        runtime yielding an empty answer would mark every model unloaded on
        the strength of a network blip.

        Each model is recorded under Ollama's reported name and, when the tag
        is `:latest`, under the bare name as well — Ollama accepts both, the
        registry may hold either, and this aliasing is Ollama grammar that
        must not leak into the observer doing the matching.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(10.0)
            ) as client:
                ps = await client.get("/api/ps")
                tags = await client.get("/api/tags")
                if ps.status_code != 200 or tags.status_code != 200:
                    return None
                resident_models = ps.json().get("models") or []
                on_disk_models = tags.json().get("models") or []
        except (httpx.HTTPError, json.JSONDecodeError):
            return None

        resident: dict[str, float] = {}
        for entry in resident_models:
            name = entry.get("name") or entry.get("model")
            if not name:
                continue
            gb = float(entry.get("size") or 0) / 1024**3
            for spelling in _spellings(name):
                resident[spelling] = gb

        on_disk: set[str] = set()
        for entry in on_disk_models:
            name = entry.get("name") or entry.get("model")
            if name:
                on_disk.update(_spellings(name))

        return RuntimeResidency(resident=resident, on_disk=frozenset(on_disk))

    # --- internals -------------------------------------------------------

    async def _post_lifecycle(self, ref: str, keep_alive: str | int) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/api/generate", json={"model": ref, "keep_alive": keep_alive}
            )
            if response.status_code == 400:
                # An embedding model. The refusal is specific to generate;
                # embed with no input moves the same weights the same way.
                response = await client.post(
                    "/api/embed", json={"model": ref, "input": [], "keep_alive": keep_alive}
                )
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(
                    detail=f"ollama lifecycle post returned {response.status_code} for {ref}"
                )

    async def _raise_for_status(self, response: httpx.Response, ref: str) -> None:
        if response.status_code < 400:
            return
        # The body has to be read before it can be inspected on a streamed
        # response, and it goes to the log rather than to the caller: it can
        # name models and paths that a public caller should not learn about.
        await response.aread()
        detail = f"ollama returned {response.status_code} for {ref}: {response.text[:500]}"
        if response.status_code == 404:
            raise ModelNotFoundError(detail=detail)
        raise NoAvailableModelError(detail=detail)
