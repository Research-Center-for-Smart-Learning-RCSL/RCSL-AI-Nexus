"""Counting a prompt with the vocabulary of the model that will read it.

The platform estimated tokens from character widths until 2026-08-17, and the
estimate was wrong by 1.34x-1.48x on prose, source and tool schemas and by
0.36x on a list of uuids. Both directions cost something. The over-count
refused a client at 140059 estimated tokens whose payload was about 99000 real
ones — inside what the model could read, outside what the estimate was judged
against — and the under-count is what precedes a prompt the runtime truncates
in silence. No single constant sits inside a spread that wide, which is the
whole argument for this port existing.

**A counter may decline to answer, and that is a supported outcome rather than
an error.** MLX serves models this host holds no GGUF for; a model registered
five minutes ago may not be pulled yet; a mount may be missing. `None` means
"cannot say", exactly as `ModelRuntimePort.residency` uses it, and the caller
falls back to the character estimate and logs which reference it happened for.
"No counter, no ceiling" is not an available state: the guardrail this feeds
runs before any hardware is committed, and it must always have an answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.entities.chat import Message, ToolDefinition


class TokenCounterPort(Protocol):
    """Exact prompt tokens for a model reference, or None if it cannot say."""

    async def prepare(self, ref: str) -> bool:
        """Build and cache whatever `ref` needs, returning whether it worked.

        Called when a model is loaded, so the first request to a newly resident
        model does not pay for reading an 11 MiB header — and so an operator
        who loads a model learns at that moment whether its vocabulary is
        available, rather than discovering weeks later that every request has
        been counted by the fallback. The answer is logged by the caller, not
        raised: a model whose vocabulary cannot be read still serves requests.
        """
        ...

    async def count_prompt(
        self, ref: str, messages: Sequence[Message], tools: Sequence[ToolDefinition]
    ) -> int | None:
        """Everything the model will read, including the runtime's own framing.

        Not the sum of the message contents. A chat template wraps every turn
        in role markers and renders the tool definitions into a preamble, and
        those tokens are read by the model and charged against its context like
        any other — measured at 211 tokens of preamble plus 23 per definition
        on `qwen3.6:35b-a3b-q8_0`, which for the 286-definition client of
        2026-08-17 is about 6800 tokens nothing was counting.

        `tools` is part of the count and not an adjustment to it, because it is
        the part an agent client grows without bound and the one field of an
        agent request that no person ever types.
        """
        ...

    async def count_parts(self, ref: str, texts: Sequence[str]) -> Sequence[int] | None:
        """Each text on its own, for describing where a refused prompt's tokens went.

        Separate from `count_prompt` because the two answer different
        questions: that one is the figure a ceiling is judged against, and this
        one is the breakdown a caller is shown when the ceiling refuses them.
        A breakdown may not be derived by subtraction from the total — framing
        belongs to no single message — and a total may not be derived by
        summing the parts, because the framing would then be missing from it.

        One call for the whole list rather than one per text: the parts of a
        refused agent conversation number in the hundreds, and the cost worth
        avoiding is the round trip to a worker thread, not the encoding.

        Only ever called on the refusal path. The common path pays for one
        count, which is what `_describe_prompt_composition` already declines to
        pay twice for the same reason.
        """
        ...
