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
import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from app.adapters.runtime.tool_support import should_send_tools
from app.adapters.runtime.transport import timeout_error
from app.adapters.runtime.validation import assert_valid_model_ref
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolDefinition,
)
from app.domain.entities.model import PullProgress, RuntimeResidency
from app.domain.exceptions import (
    DomainError,
    ModelNotFoundError,
    NoAvailableModelError,
    RuntimeCapabilityError,
    StreamInterruptedError,
)

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
_FINISH_REASONS = {
    "stop": "stop",
    "length": "length",
    "load": "stop",
    "unload": "stop",
    "tool_calls": "tool_calls",
}


def _finish_reason(done_reason: str | None, *, called_tools: bool) -> str:
    """`tool_calls` wins over whatever Ollama reported.

    Ollama ends a generation that produced tool calls with `done_reason: stop`,
    which is true of the model and wrong for the client: an OpenAI agent loop
    branches on exactly this field to decide whether to execute a call or to
    show the user an answer. Told "stop" it treats the turn as finished and the
    calls are never run, so the conversation stalls with the model waiting on
    results that nobody will produce.

    `called_tools` means "calls are being forwarded", never "the runtime
    mentioned tool calls". The inverse mistake stalls the loop from the other
    end: `tool_calls` with an empty list leaves the client waiting to execute
    something it was never given, and with no content to fall back on.

    **`length` outranks it in turn** (2026-08-09). A generation cut off at the
    token ceiling or the context window may have stopped part way through a
    call's `arguments`, leaving a JSON fragment; reporting `tool_calls` there
    invites the client to execute something incomplete, and reports a truncated
    turn as a finished one on `/v1/responses`, whose `response.incomplete` event
    keys on this value. `stop` is the only reason `tool_calls` needs to
    override, because `stop` is what a *successful* call-producing generation
    reports.
    """
    mapped = _FINISH_REASONS.get(done_reason or "stop", "stop")
    if called_tools:
        return "length" if mapped == "length" else "tool_calls"
    if mapped == "tool_calls":
        logger.warning("ollama reported done_reason=tool_calls with no usable calls")
        return "stop"
    return mapped


def _set_num_ctx(options: dict[str, Any], context_length: int | None) -> None:
    """Tell Ollama how much context to size the runner for.

    Without it Ollama allocates for the model's *own* declared maximum, which
    for `gemma4:31b-it-qat` is 262144 tokens and predicted 55.8 GiB — enough
    that loading it evicted every other resident model, taking `assist` and
    `embedding` down with it (PROGRESS.md 2026-08-07). The platform never sends
    more than `MAX_CONTEXT_LENGTH`, and each model registers its own ceiling
    below that, so the runtime was reserving for four times the largest request
    it will ever see.

    **This went unnoticed for three months because the resident model hid it.**
    `glm-4.7-flash` uses multi-head latent attention with a single KV head, so
    even 202752 tokens of context cost little; the first dense model with
    ordinary attention made the same missing argument fatal.

    Zero and negative are treated as absent rather than sent. The column
    defaults to 0, so a row registered before the profile was required would
    otherwise ask Ollama for a zero-length context.
    """
    if context_length is not None and context_length > 0:
        options["num_ctx"] = context_length


def _sampling_options(sampling: SamplingOptions | None) -> dict[str, Any]:
    """Ollama's `options` names for the parameters the caller set.

    Only what was actually asked for. Sending a value for every field would
    replace Ollama's own defaults with this module's opinion of them, and the
    two are not the same list from one release to the next.
    """
    if sampling is None:
        return {}
    options: dict[str, Any] = {}
    if sampling.temperature is not None:
        options["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        options["top_p"] = sampling.top_p
    if sampling.seed is not None:
        options["seed"] = sampling.seed
    if sampling.stop:
        options["stop"] = list(sampling.stop)
    return options


def _tool_payload(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _arguments_for_upstream(arguments: str) -> Any:
    """Ollama takes a tool call's arguments as an object; the domain holds text.

    Undecodable arguments are refused here, loudly, as a capability this
    runtime does not have. The first version sent the raw string instead, on
    the theory that a conversation whose model once emitted malformed JSON
    should stay replayable and Ollama should decide — **measured false on
    0.32.4** (2026-08-05): Ollama types the field as an object and answers 400
    for any string, malformed or not, so the fallback had no input on which it
    could succeed. Worse than useless, actively wrong: that 400 came back
    through `_raise_for_status` as `no_available_model`, whose documented
    remedy is retry, for a failure that is permanent — a client following the
    docs would replay the same conversation forever.

    `RuntimeCapabilityError` is the honest classification: the arguments are
    legal on the wire (they are model output and the schema deliberately admits
    them), the MLX adapter can carry them (its server takes the string), and
    this runtime genuinely cannot. A 400 tells the caller the request itself is
    the problem — repair or drop the turn — where a 503 told them to retry it.
    """
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeCapabilityError(
            detail=f"ollama takes tool-call arguments as a JSON object and cannot "
            f"carry arguments that do not parse: {arguments[:200]!r}"
        ) from exc


def _message_payload(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        # `id` goes back too. This adapter minted it, the tool message's
        # `tool_call_id` cites it, and a build that pairs on ids needs both
        # halves of the pair present — omitting it here pointed the result at
        # an id that existed nowhere in the history. Verified accepted on
        # 0.32.4 (2026-08-05); an older build ignores an unknown field, which
        # is the same argument the two spellings below already rest on.
        payload["tool_calls"] = [
            {
                "id": c.id,
                "function": {"name": c.name, "arguments": _arguments_for_upstream(c.arguments)},
            }
            for c in message.tool_calls
        ]
    if message.role is MessageRole.TOOL:
        # Both spellings. Ollama has paired a tool result to its call by name,
        # and carries the id on newer builds; sending each under the key that
        # build expects costs nothing, because a Go handler ignores a field it
        # does not know. Sending only one would work on exactly one of them.
        if message.name:
            payload["tool_name"] = message.name
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
    return payload


def _parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """The id is minted here rather than taken from Ollama, on purpose.

    It is the handle a client uses to pair its tool result back to the call, so
    it has to survive the round trip, which means it must be unique within a
    conversation rather than merely within a chunk — an index would collide
    across turns and pair a result with the wrong call.

    **Whether Ollama supplies one at all is version-dependent**, which is the
    reason not to depend on it. It supplied none when this was written; 0.32.4
    supplies `call_85x6g8ts`-shaped ids (observed 2026-08-05). Neither the
    presence nor the uniqueness of that field is part of any contract Ollama
    publishes, and a runtime that restarted the sequence per turn would produce
    exactly the collision above — silently, as a coherent conversation about the
    wrong thing. Minting unconditionally costs nothing and depends on nothing:
    the id is opaque to the client, which only has to echo back what we sent.
    """
    if not isinstance(raw, list):
        return ()

    calls: list[ToolCall] = []
    for entry in raw:
        function = (entry or {}).get("function") or {}
        name = function.get("name")
        if not name:
            # A call with no name is one no client can execute. Dropped rather
            # than forwarded as an empty call, which would look executable.
            logger.warning("ollama emitted a tool call with no function name, ignoring")
            continue
        arguments = function.get("arguments")
        calls.append(
            ToolCall(
                id=f"call_{uuid.uuid4().hex[:24]}",
                name=name,
                # Back to text, the form the domain holds and the wire carries.
                # `separators` so the bytes match what `sse.py` would produce
                # for the same object, since a client may compare them.
                arguments=(
                    arguments
                    if isinstance(arguments, str)
                    else json.dumps(arguments or {}, separators=(",", ":"))
                ),
            )
        )
    return tuple(calls)


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
        tools: Sequence[ToolDefinition] = (),
        tool_choice: ToolChoice | None = None,
        sampling: SamplingOptions | None = None,
        context_length: int | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream a completion.

        An async generator, so it is declared without `async def` in the port
        and called without await. The `finally` inside the `async with` is
        what closes the upstream request when a client disconnects; without
        it Ollama keeps generating for someone who has already gone.
        """
        assert_valid_model_ref(ref)
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        if max_tokens is not None:
            # Stopping at the source beats counting chunks and cutting the
            # stream: the model stops generating rather than producing tokens
            # nobody reads.
            options["num_predict"] = max_tokens
        options.update(_sampling_options(sampling))

        payload: dict[str, Any] = {
            "model": ref,
            "messages": [_message_payload(m) for m in messages],
            "stream": True,
        }
        if options:
            payload["options"] = options
        # Consulted before the emptiness check, not after it. Short-circuiting
        # on `tools` meant a `tool_choice` the runtime cannot honour went
        # unrefused whenever the caller sent no tools with it, which is 200 and
        # prose where every piece of documentation promises a 400.
        send_tools = should_send_tools(tool_choice, "ollama")
        if tools and send_tools:
            payload["tools"] = _tool_payload(tools)
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
        called_tools = False
        forwarded_calls: set[tuple[str, str]] = set()
        """(name, arguments) of every call already yielded, consulted only on
        the terminal event. On the build this was written against, calls arrive
        on interim events and the terminal event repeats nothing — but that is
        observed behaviour, not a contract, and a build that restated the
        turn's calls in its done event would have an agent execute every one of
        them twice. Side effects make that the expensive direction to be wrong
        in, so the terminal event is filtered against what was already sent.
        Interim events are never filtered: a model that genuinely asks for the
        same call twice puts both in its own messages, and those go through."""
        # A timeout here is a `DomainError` or it is a 500. Nothing above this
        # layer handles an httpx exception: it escapes the router's handler,
        # which only knows `DomainError`, so before this the honest and
        # reachable case of "the prompt took longer to evaluate than the read
        # timeout allows" surfaced as an unhandled error with no envelope, or
        # mid-stream as a connection that simply stopped without `[DONE]`.
        #
        # 503 rather than a distinct code: the caller's remedy is to retry, and
        # a retry usually works, because the prompt is now in the runtime's
        # prefix cache and evaluation is nearly free the second time.
        received_any = False
        try:
            async with (
                httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client,
                client.stream("POST", "/api/chat", json=payload) as response,
            ):
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    received_any = True
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
                    calls = _parse_tool_calls(message.get("tool_calls"))

                    if event.get("done"):
                        saw_done = True
                        repeated = tuple(
                            c for c in calls if (c.name, c.arguments) in forwarded_calls
                        )
                        if repeated:
                            logger.warning(
                                "ollama repeated %s already-forwarded tool call(s) "
                                "in its done event for %s, dropping the repeats",
                                len(repeated),
                                ref,
                            )
                            calls = tuple(c for c in calls if c not in repeated)
                        if calls:
                            called_tools = True
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
                            tool_calls=calls,
                            finish_reason=_finish_reason(
                                event.get("done_reason"), called_tools=called_tools
                            ),
                            token_count=correction,
                            # Reported once, here, for the whole request.
                            # Ollama has always sent it; nothing read it until
                            # 2026-08-04, so every prompt was free of quota.
                            prompt_tokens=int(event.get("prompt_eval_count") or 0),
                        )
                        return

                    if delta or reasoning or calls:
                        # Reasoning counts. Ollama's `eval_count` includes the
                        # thinking tokens, so excluding them here would make the
                        # end-of-stream correction re-bill every one of them.
                        # Tool calls are decoded tokens too, and a generation
                        # that is nothing but a call would otherwise be counted
                        # as producing nothing until the terminal correction.
                        counted += 1
                        if calls:
                            called_tools = True
                            forwarded_calls.update((c.name, c.arguments) for c in calls)
                        yield CompletionChunk(
                            delta=delta, reasoning=reasoning, tool_calls=calls, token_count=1
                        )

                if not saw_done:
                    # The stream ended without a terminal event: the model was
                    # evicted, Ollama restarted, or the read timeout fired.
                    # Returning quietly would let the caller record a complete
                    # generation and report "stop" to the client.
                    raise StreamInterruptedError(
                        detail=f"ollama stream for {ref} ended without a done event"
                    )
        except httpx.TimeoutException as exc:
            raise timeout_error("ollama", ref, exc, self._timeout, mid_stream=received_any) from exc

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

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
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
        await self._post_lifecycle(ref, keep_alive=self._keep_alive, context_length=context_length)

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

    async def _post_lifecycle(
        self, ref: str, keep_alive: str | int, context_length: int | None = None
    ) -> None:
        # The load is where Ollama sizes the runner, so this is the call that
        # decides how much memory the weights bring with them. An unload does
        # not size anything and passes nothing.
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        body: dict[str, Any] = {"model": ref, "keep_alive": keep_alive}
        if options:
            body["options"] = options

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post("/api/generate", json=body)
            if response.status_code == 400:
                # An embedding model. The refusal is specific to generate;
                # embed with no input moves the same weights the same way.
                response = await client.post("/api/embed", json={**body, "input": []})
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
