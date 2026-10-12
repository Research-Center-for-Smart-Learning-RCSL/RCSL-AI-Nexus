"""Bounded Tier 2 execution owned and settled by the selected node agent."""

from __future__ import annotations

import asyncio
from typing import Any

from app.application.use_cases.route_chat_request.compaction_tier2 import (
    SUMMARY_MAX_BYTES,
    SUMMARY_OUTPUT_TOKENS,
    SUMMARY_TIMEOUT_SECONDS,
)
from app.domain.ports.token_counter_port import TokenCounterPort
from app.node_agent.dispatch import Completed, Outcome, Relay, RuntimeRefused, Sink, Uncertain


class _SummarySink:
    def __init__(self, sink: Sink) -> None:
        self.sink = sink
        self.parts: list[str] = []
        self.size = 0
        self.overflow = False

    def emit(self, event: dict[str, Any]) -> None:
        # Keep reading to terminal evidence after overflow. No partial summary
        # crosses to the caller, and buffering has a separate hard byte cap.
        if self.overflow or event.get("type") != "line":
            return
        message = (event.get("data") or {}).get("message") or {}
        text = message.get("content") or ""
        self.size += len(text.encode("utf-8"))
        if self.size > SUMMARY_MAX_BYTES:
            self.overflow = True
            self.parts.clear()
        else:
            self.parts.append(text)

    async def checkpoint(self, observed: dict[str, Any]) -> None:
        await self.sink.checkpoint(observed)


def bounded_summary(
    relay: Relay,
    counter: TokenCounterPort,
    ref: str,
    *,
    timeout_s: float = SUMMARY_TIMEOUT_SECONDS,
) -> Relay:
    async def run(sink: Sink) -> Outcome:
        collected = _SummarySink(sink)
        outcome: Outcome | None = None
        try:
            async with asyncio.timeout(timeout_s):
                outcome = await relay(collected)
                if not isinstance(outcome, Completed):
                    return outcome
                if collected.overflow:
                    return RuntimeRefused(outcome.terminal, "summary_output_bytes_exceeded")
                text = "".join(collected.parts).strip()
                counts = await counter.count_parts(ref, [text])
                runtime_count = outcome.terminal.get("eval_count")
                if (
                    not text
                    or counts is None
                    or len(counts) != 1
                    or counts[0] > SUMMARY_OUTPUT_TOKENS
                    or not isinstance(runtime_count, int)
                    or runtime_count > SUMMARY_OUTPUT_TOKENS
                    or outcome.terminal.get("done_reason") == "length"
                ):
                    return RuntimeRefused(outcome.terminal, "summary_output_budget_exceeded")
                sink.emit({"type": "summary", "text": text})
                return Completed(outcome.terminal, result={"summary": text})
        except TimeoutError:
            if isinstance(outcome, Completed):
                return RuntimeRefused(outcome.terminal, "summary_output_count_deadline")
            # Cancelling a send is not runtime terminal evidence. Retain the
            # node-wide block even though this task stops holding a local slot.
            return Uncertain("summary_deadline")

    return run
