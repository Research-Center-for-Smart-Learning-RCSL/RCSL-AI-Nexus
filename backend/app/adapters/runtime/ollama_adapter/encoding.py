"""Ollama request encoding."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolDefinition,
)
from app.domain.exceptions import (
    RuntimeCapabilityError,
)

DEFAULT_KEEP_ALIVE = "-1"


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


def tool_payload(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
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


def message_payload(message: Message) -> dict[str, Any]:
    """One message in Ollama's spelling.

    Public, unlike its MLX counterpart, because a second reader arrived that
    has to agree with it exactly: `adapters/tokenizer/gguf_token_counter.py`
    renders this payload through the model's chat template to count what the
    prompt will cost. A private copy there would be a second spelling of the
    wire shape, and the first time the two disagreed the guardrail would be
    judging a payload the runtime never receives.
    """
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
