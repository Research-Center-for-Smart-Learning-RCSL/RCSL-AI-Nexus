"""The one usage row an agent-backed attempt is billed by (design R6, S6, T3,
U2 and revision 6 on #24).

Pure, and the only place the row is built: the gateway's live finalizer and
the admin sweeper both call it on the same stored facts, so whichever inserts
first writes the row the other would have written. The row is keyed by the
attempt, and inserted once.

- **Totals** come from the agent's terminal commit, never from what the
  gateway happened to see. `runtime_final` is the runtime's raw
  `eval_count` and `prompt_eval_count`; `estimated_from_chunks` is a chunk
  count, an observation and never a bound; `unavailable` is 0, labelled.
- **Prompt basis** is independent of the output source: the runtime's figure
  when it reported one, otherwise the agent's own count and its basis.
- **`completed`** keeps its meaning, the client received the whole response:
  true only when the gateway committed that. `runtime_completed` is the
  runtime reaching `done`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

BILLABLE_STATES = frozenset({"completed", "failed"})
"""Terminal states that ran or may have run. `cancelled_unsent` provably sent
nothing and is never billed; an unfinished or unknown attempt is billed only
once it reaches one of these."""

PROMPT_BASES = frozenset({"runtime_final", "exact_counter", "estimate"})


@dataclass(frozen=True, slots=True)
class SettledUsage:
    tokens: int
    prompt_tokens: int
    totals_source: str
    prompt_tokens_basis: str
    runtime_completed: bool
    latency_ms: int
    completed: bool
    at: datetime


def settle_usage(
    *,
    state: str,
    terminal: dict[str, Any] | None,
    observed: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    started_at: datetime,
    delivered: bool | None,
) -> SettledUsage:
    terminal = terminal or {}
    observed = observed or {}
    provenance = provenance or {}

    eval_count = _int(terminal.get("eval_count"))
    if state == "completed" and eval_count is not None:
        tokens, source = eval_count, "runtime_final"
    else:
        chunks = _int(terminal.get("observed_chunk_count"))
        if chunks is None:
            chunks = _int(observed.get("observed_chunk_count"))
        if chunks is not None:
            tokens, source = chunks, "estimated_from_chunks"
        else:
            tokens, source = 0, "unavailable"

    reported_prompt = _int(terminal.get("prompt_eval_count"))
    counted = _int(provenance.get("counted"))
    if source == "runtime_final" and reported_prompt is not None:
        prompt_tokens, basis = reported_prompt, "runtime_final"
    elif counted is not None and provenance.get("basis") in PROMPT_BASES:
        prompt_tokens, basis = counted, str(provenance["basis"])
    else:
        prompt_tokens, basis = 0, "estimate"

    total_ns = _int(terminal.get("total_duration"))
    elapsed = _int(terminal.get("observed_elapsed_ms"))
    if elapsed is None:
        elapsed = _int(observed.get("observed_elapsed_ms"))
    latency_ms = total_ns // 1_000_000 if total_ns is not None else (elapsed or 0)

    return SettledUsage(
        tokens=tokens,
        prompt_tokens=prompt_tokens,
        totals_source=source,
        prompt_tokens_basis=basis,
        runtime_completed=state == "completed",
        latency_ms=latency_ms,
        # NULL is pending or unknown, never a settled failure (revision 6); it
        # starts false and only reconciliation may turn it true.
        completed=delivered is True,
        at=started_at + timedelta(milliseconds=latency_ms),
    )


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
