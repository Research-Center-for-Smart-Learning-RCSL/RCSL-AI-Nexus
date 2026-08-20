"""Prompt truncation and estimate-drift diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    Message,
    ToolDefinition,
)
from app.domain.exceptions import (
    COUNT_BY_TOKENIZER,
)

from .estimates import (
    _estimated_prompt_tokens,
    _estimated_tool_tokens,
)

logger = logging.getLogger("app.application.use_cases.route_chat_request")


def _warn_if_prompt_was_truncated(
    prompt_tokens: int,
    context_length: int,
    *,
    estimated: int,
    basis: str,
    request_id: str | None,
    actor: str,
) -> None:
    """The backstop for the estimate above being wrong in the unsafe direction.

    Ollama evaluates at most `num_ctx / 2` prompt tokens and drops the rest
    without saying so — `done_reason` is `length`, which is also what a
    generation that filled its budget reports, so nothing downstream can tell
    the two apart. The caller gets a fluent answer to a conversation whose
    beginning the model never saw, and the only thing wrong with the response
    is that it is wrong.

    `RouteChatRequest._refuse_what_this_target_would_truncate` refuses against
    this same boundary before any hardware is committed, which means reaching it
    here is not a caller's problem to solve but a signal that the estimator
    under-counted their content: the refusal judged an estimate, and this judges
    what the tokenizer actually charged. Logged rather than raised: the answer
    has already been produced and generated tokens have already been paid for,
    so refusing here would bill for work and return nothing. The request id
    makes it correlate with the caller's report, which is how the 2026-08-14
    incident was diagnosed in the first place.

    The drift line below fires far more often and refuses nothing. It exists
    because the estimate was, until 2026-08-17, visible only when it refused a
    request or when this warning fired — so an estimator that was wrong in the
    *safe* direction was invisible, and being wrong in the safe direction still
    costs a caller their context. Measuring that took reconstructing it by hand
    from `usage_records` after the fact.
    """
    if not prompt_tokens or context_length <= 0:
        # Zero means the stream never reached its terminal chunk, so there is
        # no figure to judge — not that nothing was read.
        return
    if prompt_tokens < context_length // 2:
        # Only here. Past the boundary `prompt_eval_count` reports what the
        # runtime *evaluated*, which saturates at num_ctx/2, so the ratio below
        # would divide by a number that stopped tracking the prompt: a 115000
        # prompt estimated at 100000 and cut to 4096 reads as a 24x over-count
        # when the estimator in fact under-counted. That is the one direction
        # this signal exists to catch, inverted.
        _log_estimate_drift(
            prompt_tokens, estimated=estimated, basis=basis, request_id=request_id, actor=actor
        )
        return
    logger.warning(
        "prompt likely truncated by the runtime: prompt_tokens=%s reached num_ctx/2=%s "
        "(estimated %s) request_id=%s actor=%s — the token estimate under-counted this "
        "content and the model did not see the whole conversation",
        prompt_tokens,
        context_length // 2,
        estimated,
        request_id,
        actor,
    )


ESTIMATE_DRIFT_BAND = (0.9, 1.65)
"""The estimate-to-actual ratios already known to be normal, which are not news.

A symmetric tolerance was the wrong shape for this. The estimator does not sit
near 1.0 and is not meant to: measured against qwen36 it runs 1.22x to 1.61x
high on every kind of content this platform serves, and 0.34x to 0.91x on dense
ASCII. Any threshold tight enough to call 1.2x a deviation fires on essentially
every request, and one loose enough to stay quiet says nothing about the
direction that matters.

So the band is the measured spread, and a line is logged only outside it. Below
0.9 the estimator is under-counting by more than any sample did, which is what
precedes a silent truncation. Above 1.65 it is over-counting by more than any
sample did, which costs callers capacity they paid for.

**The top was 1.5 until 2026-08-18, taken from that day's 1.47x maximum, and
the third measurement put English prose at 1.61x.** The two are not in
conflict — the header above records why, the ratio being a property of the
sample rather than a constant of the content type — but a band that excludes a
measured sample turns this instrument into the noise it was shaped to avoid: on
an `estimate` basis, ordinary prose would have logged over-counting on
essentially every request. The bottom is deliberately not the measured minimum
for the opposite reason: 0.34x is a real dense-ASCII figure, and under-counting
is the direction that ends in a silent truncation, so it is meant to be
reported.

**This would not have fired on 2026-08-17, and should not have.** That refusal
was at 1.21x — ordinary calibration, not drift. What was wrong that day was a
ceiling with no margin for a known over-count, and the fix for it is
`RouteChatRequest._refuse_what_this_target_would_truncate`, not this line. An
earlier draft of this docstring claimed the incident as its motivation while the
threshold it set would have stayed silent through it.
"""


TOOL_SHARE_WARNING = 0.5
"""When a client's tool definitions are worth warning about, as a share of the
estimate. Half, because below that the conversation is still the thing that will
reach the ceiling and the ordinary remedies apply."""


def _warn_if_tools_dominate(
    counted: int,
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    ceiling: int,
    request_id: str | None,
    actor: Actor,
) -> None:
    """Say so *before* the client hits the ceiling, not when it does.

    A tool list is fixed for a session, resent whole on every turn, and invisible
    to the person driving the agent -- so a client spending most of its window on
    tool definitions looks, from the outside, like a platform that refuses short
    conversations. On 2026-08-17 one arrived with 286 definitions worth an
    estimated 122870 tokens, more than the whole ceiling on its own, and could
    not send a four-message conversation. The refusal named the share, which is
    what solved it; nothing had named it on the many requests that succeeded
    first.

    **Both conditions, not either.** A short request can be 90% tools and cost
    nothing, so the share alone fires on requests nobody needs to hear about. The
    absolute floor is a tenth of the ceiling, which is the point at which the
    list is spending real window rather than merely most of a small request.

    This logs on every turn while the condition holds, which for an agent loop is
    every request in the task. That is deliberate: the alternative is per-process
    state to deduplicate a line that stops the moment the client is fixed, and
    the drift log above already made the same trade.

    **The share is computed entirely from estimates, and the exact total is
    reported beside it rather than divided into it.** Dividing an estimated
    tool figure by an exact total mixes bases that differ by the factor this
    file's tables record: for the 286-definition client of 2026-08-17 that is
    140059 over about 99000, and the line would have read "tool definitions are
    141% of this prompt". A share above the whole is not a rounding error, it
    is a sentence nobody can act on — and the same mismatch moves the trigger,
    firing on prompts whose definitions are honestly well under half.

    Measuring the share exactly would mean encoding the definitions a second
    time on the common path, for a payload where they are by definition the
    largest part, and this is a log line. So the cheap absolute floor is the
    gate: below a tenth of the ceiling nothing is computed at all, and the full
    estimate — the one pass this path was written to avoid — is paid only by
    the payloads that were about to provoke the warning anyway.
    """
    if not tools or ceiling <= 0:
        return
    tool_tokens = _estimated_tool_tokens(tools)
    if tool_tokens < ceiling // 10:
        return
    estimated, _ = _estimated_prompt_tokens(messages, tools)
    if estimated <= 0:
        return
    share = tool_tokens / estimated
    if share < TOOL_SHARE_WARNING:
        return
    logger.warning(
        "tool definitions are about %.0f%% of this prompt: ~%s estimated tokens in %s "
        "definitions, against a counted %s and a ceiling of %s, resent every turn "
        "request_id=%s actor=%s",
        share * 100,
        tool_tokens,
        len(tools),
        counted,
        ceiling,
        request_id,
        actor.display,
    )


EXACT_DRIFT_ALLOWANCE = (-16, 64)
"""How far an exact count may sit from `prompt_eval_count` before it is news.

Tokens, not a ratio, because what separates the two is a constant rather than a
share: the chat template this platform renders emits a `<think>` opener Ollama
does not, and Ollama's tool preamble is a little shorter than the template's.
Measured across six payload shapes on 2026-08-17 the gap was +2 with no tools,
+12 with 12 definitions and with 60, and +14 for a conversation carrying a tool
call and its result — constant in every case, which is why a ratio would be the
wrong instrument at both ends of the size range.

The window is asymmetric for the reason every threshold in this file is: an
under-count is the direction that ends in a prompt the runtime truncates in
silence, so it is allowed sixteen tokens and the safe direction is allowed
sixty-four. Anything outside it is a change in what the runtime builds around a
prompt, and the point of logging it is that nothing else on this platform would
notice one.
"""


def _log_estimate_drift(
    prompt_tokens: int, *, estimated: int, basis: str, request_id: str | None, actor: str
) -> None:
    """One line when the count leaves the spread it was measured to have.

    INFO rather than WARNING: on its own it is a calibration observation, not a
    fault, and the fault it precedes has its own warning above. The caller is
    told nothing — by the time this runs their answer has already been produced.

    **This is the instrument that proves the tokeniser, and it is the only
    one.** An exact count is exact against the vocabulary it was built from; a
    vocabulary bound to the wrong model, a pre-tokeniser scheme that splits
    text differently, or a runtime upgrade that changes the framing would each
    produce a confident figure that no test in this repository could catch,
    because the ground truth lives in the runtime. This line is where the two
    are compared, on every request that ran to completion.

    Only reached for prompts the runtime read whole; see the caller for why a
    truncated one cannot be judged this way.
    """
    if not estimated:
        return
    if basis == COUNT_BY_TOKENIZER:
        low, high = EXACT_DRIFT_ALLOWANCE
        difference = estimated - prompt_tokens
        if low <= difference <= high:
            return
        logger.info(
            "exact count disagrees with the runtime by %+d tokens: counted=%s actual=%s "
            "(expected %+d to %+d) request_id=%s actor=%s — %s",
            difference,
            estimated,
            prompt_tokens,
            low,
            high,
            request_id,
            actor,
            "the vocabulary or the framing no longer describes what this runtime builds",
        )
        return
    ratio = estimated / prompt_tokens
    low_ratio, high_ratio = ESTIMATE_DRIFT_BAND
    if low_ratio <= ratio <= high_ratio:
        return
    logger.info(
        "token estimate outside its measured band: estimated=%s actual=%s ratio=%.2f "
        "(expected %.2f-%.2f) request_id=%s actor=%s — %s",
        estimated,
        prompt_tokens,
        ratio,
        low_ratio,
        high_ratio,
        request_id,
        actor,
        "under-counting, which is what precedes a silent truncation"
        if ratio < low_ratio
        else "over-counting, which refuses requests the model would have served",
    )
