"""Prompt estimates, lower bounds, and composition."""

from __future__ import annotations

import json
from collections.abc import Sequence
from math import ceil

from app.domain.entities.chat import (
    Message,
    ToolDefinition,
)
from app.domain.exceptions import (
    COUNT_BY_LOWER_BOUND,
    COUNT_BY_TOKENIZER,
)

ASCII_CHARS_PER_TOKEN = 3.0
WIDE_CHARS_PER_TOKEN = 1.1
"""How many characters of each kind one token is assumed to hold.

Measured against the tokenizer itself on 2026-08-14, by sending samples through
gemma4-31b-q8 and reading `prompt_eval_count`:

| content              | chars/token |
|----------------------|-------------|
| English prose        | 4.57        |
| JavaScript and HTML  | 3.59        |
| JSON tool schema     | 2.31        |
| Chinese with code    | 2.27        |
| Traditional Chinese  | 1.38        |
| Minified JavaScript  | **1.15**    |

The single figure of 4.0 this replaced was measured on none of it. It held for
English prose and under-counted everything else — a Traditional Chinese
conversation by 2.9x, which is why a Codex session on 2026-08-14 was admitted
at roughly 115,000 tokens against a ceiling of 65,536 and would have been
silently truncated by the runtime a few turns later.

**That table was superseded on 2026-08-17 and came back into force on
2026-08-21, which nothing noticed until 2026-09-02.** It was measured on
`gemma4-31b`, and `gemma4-31b-q8` — which has served `chat` and `code` since
2026-08-21 — carries the same 262,144-entry vocabulary, so it is this table
rather than the one below that describes what the estimator is now applied to.
(Inferred from the vocabulary rather than re-measured: the two builds are the
same model at two quantisations and their headers disagree only in which key
carries the pre-tokeniser name.) The table below was measured against
qwen36-35b-a3b-q8, which held both capabilities for five days:

| content              | chars/token | estimate runs |
|----------------------|-------------|---------------|
| English prose        | 4.40        | 1.47x high    |
| Python source        | 4.33        | 1.45x high    |
| TypeScript source    | 4.03        | 1.34x high    |
| Markdown             | 3.88        | 1.29x high    |
| JSON tool schema     | 3.67        | 1.22x high    |
| Traditional Chinese  | 1.49        | 1.36x high    |
| Minified JavaScript  | 2.72        | 0.91x         |
| base64 blob          | 1.39        | 0.46x         |
| git sha table        | 1.21        | 0.40x         |
| UUID list            | **1.02**    | **0.34x**     |

**Two tables in this repository gave different figures for the same content
types, and 2026-08-18 settled why.** `docs/PROGRESS.md`'s 2026-08-17 catalogue
reads 1.34x-1.48x over prose, source and tool schemas with UUIDs at 0.36x; the
table above reads 1.22x-1.47x with UUIDs at 0.34x. Re-measured that day against
this same tokenizer on freshly written samples — English prose 1.61x, Python
1.47x, TypeScript 1.25x, Markdown 1.22x, a twelve-tool JSON schema 1.24x, a
120-line UUID list 0.37x, each net of the twelve tokens the chat template costs
on an empty turn — and the third set agrees with neither to two decimal places.

**Neither table is wrong. The ratio is a property of the sample, not a constant
of the content type**, and prose is the widest: how much of it is common short
words decides most of the figure. So the two-decimal precision both tables
carry is spurious, and the honest reading of all three is a range — roughly
1.2x-1.6x over natural language and source, and 0.34x-0.40x over dense
identifiers. That range is what the constants below have to survive, and it is
wider than either table alone suggested.

The constants are not retuned to it, and the second table is why: qwen36 is
*both* more efficient than gemma4 on everything this platform serves and more
fragmented on dense identifiers, so the gap between the honest case and the
pathological one grew rather than shrank. 3.0 cannot sit inside it. Raising it
to recover the 1.2x-1.6x over-count would deepen the 0.34x under-count, and the
under-count is the direction that ends in a silent truncation.

What the over-count costs is real and was paid twice on 2026-08-17. A Codex
session at roughly 82,000 real tokens estimated at 99,429 and was refused by a
98,304 ceiling the model would have served. And a second client that evening was
refused at 140,059 estimated, of which 122,870 was 286 tool definitions —
**measured against the tokenizer the same night, that payload was about 99,000
real tokens**, inside the 131,072 the model can now read and outside the 122,880
the estimate is judged against. The ceiling that refused it was the estimator,
not the hardware.

Two rows measured that night, on payloads shaped like the ones that were
refused rather than on clean samples of one content type:

| content                                   | chars/token | estimate runs |
|-------------------------------------------|-------------|---------------|
| OpenAI function tools, long snake_case    | 4.24        | 1.41x high    |
| Chinese runbook (CJK prose + shell + paths)| 1.71       | 1.00x         |

The second is not a correction of the Traditional Chinese row above, which was
pure prose; it is what a Chinese-speaking operator's payload actually looks like,
and the two errors happen to cancel in it. The first says the tool definitions
that fill an agent's window are over-counted like everything else, so the client
that could not send an empty conversation had more room than it was told.

**Everything above describes the fallback now, not the ceiling** — except that
for `chat` and `code` the fallback *is* the ceiling, and has been since
2026-08-21. Since 2026-08-17 a request is counted with the vocabulary and chat
template of the model that will read it, taken out of that model's own weights
file (`adapters/tokenizer/gguf_token_counter.py`), and measured against the
runtime it agrees to within a constant of about a dozen tokens. The tables here
are kept because they are what the estimator still does on the paths where no
vocabulary can be resolved, and because they are the record of why no retuned
constant was an acceptable answer.

**That list of paths was written as a list of edge cases and one of them is now
the main road.** It read "an MLX target, a model registered but not pulled, a
host without the model store mounted". The fourth, unlisted because it had not
happened yet: **a model whose pre-tokenizer is not in `KNOWN_PRE_TOKENIZERS`**.
`gemma4:31b-it-q8_0` declares `tokenizer.ggml.pre = gemma4`, the allowlist holds
`qwen2` and `qwen35`, so `GgufTokenCounter.prepare` refuses it and every `chat`
and `code` request has been estimated rather than counted since the day that
model came back. Measured 2026-09-02 against the live blob store: gemma4 false,
qwen2.5:7b true, qwen3.6:35b-a3b-q8_0 true, qwen3.8:27b-q4_K_M true. So the
exactness this section says supersedes the tables currently applies to `assist`
and to the `chat` fallback and to nothing else. Tracked in
`docs/roadmap/decisions.md`; measurement in `docs/PROGRESS.md` 2026-09-02.

What is also fixed is a ceiling that knows which model it is protecting; see
`RouteChatRequest._refuse_what_this_target_would_truncate`.

**Two characters per token is not a safe floor either, and no single number
is.** Minified JavaScript is denser than Chinese; punctuation and short
identifiers each cost a token. A constant safe for that case would price
ordinary prose at a quarter of its real capacity, so these values are chosen to
be honest for the content this platform actually serves — prose, source, and
CJK — and are knowingly optimistic for a pathological payload. What keeps that
from becoming a silent truncation is `_warn_if_prompt_was_truncated` below, not
this estimate.
"""


def _estimated_tokens(text: str) -> int:
    """Characters weighted by width, which is the cheapest signal that
    correlates with tokenizer density: scripts outside ASCII are near one token
    per character in every tokenizer this platform will meet, and ASCII is not.
    """
    if text.isascii():
        # The common case, and the one worth not walking in Python. A 286-tool
        # payload is half a megabyte of JSON that `json.dumps` has already made
        # ASCII, and counting it character by character costs about 25 ms on
        # the event loop — paid before a concurrency slot is even taken.
        return ceil(len(text) / ASCII_CHARS_PER_TOKEN)
    ascii_chars = sum(1 for c in text if c.isascii())
    wide_chars = len(text) - ascii_chars
    return ceil(ascii_chars / ASCII_CHARS_PER_TOKEN + wide_chars / WIDE_CHARS_PER_TOKEN)


def _estimated_tool_tokens(tools: Sequence[ToolDefinition]) -> int:
    """What the client's tool list costs, on its own.

    A tool definition's `parameters` is arbitrary JSON, so it is measured by
    serialising it rather than by walking it: the length of the text the adapter
    will send is the figure that matters, and a nested schema has no other
    honest measure. The cost is one serialisation of a payload the adapter
    serialises again a few lines later, against a guardrail that runs before any
    hardware is committed.

    Separate from the total because this share behaves unlike the rest of the
    prompt: it is resent whole on every turn and does not shrink when the
    conversation is restarted, so it is the one part whose remedy is not "send
    a shorter conversation".
    """
    return sum(
        _estimated_tokens(tool.name)
        + _estimated_tokens(tool.description)
        + _estimated_tokens(json.dumps(tool.parameters))
        for tool in tools
    )


def _estimated_prompt_tokens(
    messages: Sequence[Message], tools: Sequence[ToolDefinition]
) -> tuple[int, int]:
    """Everything the model will read, as (total, tool definitions).

    The tool share is returned rather than recomputed because the guardrail
    needs the total and `_warn_if_tools_dominate` needs the part, and walking
    the tools twice on the common path is the cost this file already declined
    to pay in `_describe_prompt_composition`.
    """
    total = sum(_estimated_tokens(m.content) for m in messages)
    for message in messages:
        total += sum(
            _estimated_tokens(c.name) + _estimated_tokens(c.arguments) for c in message.tool_calls
        )
    tool_tokens = _estimated_tool_tokens(tools)
    return total + tool_tokens, tool_tokens


FLOOR_ASCII_CHARS_PER_TOKEN = 8.0
FLOOR_WIDE_CHARS_PER_TOKEN = 3.5
"""The most characters one token could plausibly hold, by script.

Not an estimate and not a tuned constant: a *bound*, used by the one check that
runs before a model has been chosen. Exact counting needs a vocabulary, a
vocabulary needs the target, and the target needs the routing reads that may
not happen before the concurrency slot is taken — so what runs first can only
be something no tokeniser could contradict.

Both values are roughly twice the most efficient density ever measured here:
4.57 ASCII characters per token on English prose, and 1.71 on a mixed Chinese
runbook. Doubling leaves room for a vocabulary more efficient than either, and
the cost of the margin is only that a payload between the bound and the real
ceiling waits for a slot in order to be refused by the exact count.

**Deliberately too loose to be a ceiling.** With the 4 MiB body limit above it
and a 122880-token ceiling below, this turns away a request only when it is
about a megabyte of prose or larger — which is the class of request worth
shedding without waiting for a slot, and nothing else.
"""


def _counted_phrase(basis: str, tokens: int) -> str:
    """How a figure is named in a log line and in the refusal's `detail`.

    The same distinction `ContextTooLongError` draws for the caller, spelled
    the way this file spells figures: a tilde for an approximation, none for a
    count. Kept here rather than shared with the exception because the two
    audiences differ — that one is prose for a client, this one is read beside
    the numbers in a container log — and the one thing they must agree on is
    which of the three a figure is, which is what `basis` carries.
    """
    if basis == COUNT_BY_TOKENIZER:
        return f"{tokens} tokens"
    if basis == COUNT_BY_LOWER_BOUND:
        return f"at least ~{tokens} tokens"
    return f"~{tokens} estimated tokens"


def _floor_tokens(text: str) -> float:
    """A count no tokeniser can go below, computed without walking the string.

    `str.isascii` and `str.encode` are both C-level passes, which matters
    because this runs on the event loop before any slot is taken. The
    non-ASCII arm turns UTF-8's own arithmetic into a lower bound on the
    character count: a character costing n bytes adds n-1 to the difference
    between the encoded length and the character length, and n is at most 4, so
    dividing that difference by 3 can only understate how many wide characters
    there are — which is the safe direction for a floor.
    """
    if text.isascii():
        return len(text) / FLOOR_ASCII_CHARS_PER_TOKEN
    wide = (len(text.encode("utf-8")) - len(text)) / 3
    return (len(text) - wide) / FLOOR_ASCII_CHARS_PER_TOKEN + wide / FLOOR_WIDE_CHARS_PER_TOKEN


def _floor_prompt_tokens(messages: Sequence[Message], tools: Sequence[ToolDefinition]) -> int:
    """The bound above, over everything the model will read."""
    total = sum(_floor_tokens(m.content) for m in messages)
    total += sum(
        _floor_tokens(c.name) + _floor_tokens(c.arguments) for m in messages for c in m.tool_calls
    )
    total += sum(
        _floor_tokens(tool.name)
        + _floor_tokens(tool.description)
        + _floor_tokens(json.dumps(tool.parameters))
        for tool in tools
    )
    return int(total)


def _composition_parts(messages: Sequence[Message], tools: Sequence[ToolDefinition]) -> list[str]:
    """Every piece a composition is measured over, flattened in a fixed order.

    Message contents first, then each turn's own tool calls, then the tool
    definitions — because the counter that measures them takes one list and
    returns one list, and the order is what puts the numbers back where they
    came from. One round trip to a worker thread rather than one per message:
    the conversations this runs on have hundreds of turns.
    """
    return (
        [m.content for m in messages]
        + ["".join(c.name + c.arguments for c in m.tool_calls) for m in messages]
        + [tool.name + tool.description + json.dumps(tool.parameters) for tool in tools]
    )


def _describe_prompt_composition(
    messages: Sequence[Message], tools: Sequence[ToolDefinition], counts: Sequence[int]
) -> str:
    """Where a refused prompt's tokens actually went.

    "Too long" is a fact about a request; this is the part a caller can act on.
    The three shares have three different remedies and nothing else distinguishes
    them: a conversation that grew is fixed by starting a new one, one enormous
    message by not reading that file into it, and tool definitions that dominate
    by trimming the client's tool list — for which starting a new conversation
    does nothing at all, since the definitions are resent every turn.

    On 2026-08-17 an agent was refused while re-reading a single large HTML file
    on every turn. The refusal said only that ~99429 exceeded 98304, so what
    reached the person driving it was a number with no subject, and the session
    was restarted several times before the file was recognised as the cause.

    `counts` comes from `_composition_parts` in the same order, measured either
    by the model's own vocabulary or by the character estimate. **The shares
    keep their tildes under both**, and that is not laziness: even when every
    part is counted exactly, the parts do not add up to the total, because the
    chat template's framing belongs to no single message. The figure the
    ceiling judged is the one that has to be exact; these say where it went.

    Only reached on the refusal path: the guardrail admits far more requests
    than it turns away, and the common path should not pay for the rare one.
    """
    turns = len(messages)
    message_tokens = sum(counts[:turns])
    call_tokens = sum(counts[turns : 2 * turns])
    tool_tokens = sum(counts[2 * turns :])
    # Content *and* the turn's own tool calls. An agent writing a file puts the
    # body in `tool_calls[].arguments` and leaves `content` empty, so measuring
    # content alone reported "largest ~40, 0% of the whole" for a conversation
    # that was one 60000-token patch — the exact case the share exists to name.
    largest = max(
        (counts[i] + counts[turns + i] for i in range(turns)),
        default=0,
    )
    total = message_tokens + call_tokens + tool_tokens
    # Guarded because a request can consist entirely of empty strings, and a
    # share of nothing is not a number worth printing.
    share = f", {100 * largest // total}% of the whole" if total else ""
    return (
        f"~{message_tokens} in {len(messages)} messages (largest turn ~{largest}{share}), "
        f"~{call_tokens} in prior tool calls, "
        f"~{tool_tokens} in {len(tools)} tool definitions"
    )


def _estimated_composition(messages: Sequence[Message], tools: Sequence[ToolDefinition]) -> str:
    """The composition when no vocabulary is available to count the parts."""
    parts = _composition_parts(messages, tools)
    return _describe_prompt_composition(messages, tools, [_estimated_tokens(p) for p in parts])


def _floor_composition(messages: Sequence[Message], tools: Sequence[ToolDefinition]) -> str:
    """The composition for the pre-slot refusal, on the bound's own basis.

    **The shares have to be measured the way the headline was**, and this is
    the one path where that took a third function. The bound divides ASCII by
    8.0 and the estimator by 3.0, so a refusal quoting "at least ~137500" above
    parts totalling ~366667 invites arithmetic that contradicts itself by a
    factor of 2.7 — on the only path where the caller has no exact figure to
    reconcile the two against.

    Understating every part equally leaves the shares — which is what this line
    is actually read for — unchanged, since they are ratios.
    """
    parts = _composition_parts(messages, tools)
    return _describe_prompt_composition(messages, tools, [int(_floor_tokens(p)) for p in parts])
