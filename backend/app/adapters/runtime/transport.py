"""Classifying a transport timeout, identically for both runtime adapters.

One function rather than logic in each adapter, because the classification
encodes a diagnosis and the first version diagnosed wrongly: every
`httpx.TimeoutException` was reported as "without sending a byte; the prompt
may be too long to evaluate", which is true of exactly one of the three ways a
timeout happens. Told that a runtime whose process is down (connect timeout)
or one that stalled half way through an answer (read timeout mid-stream) had
been reading a long prompt, an operator debugs the wrong thing.

Since 2026-08-05 the split is on the wire as well as in the log, because the
caller's remedy differs per case (the reason the codes were split at all):

- connect timeout → `no_available_model`: the runtime process is down or
  drowning; retrying into it changes nothing an administrator does not.
- read timeout before any bytes → `runtime_timeout`: prompt evaluation
  outran the read timeout. An unchanged retry is unlikely to succeed and the
  remedy is to send less. **This paragraph said the opposite until
  2026-09-02** — that an immediate retry usually succeeds off the prefix
  cache — which was measured wrong on 2026-08-14 by aborting a cold prefill
  part way and re-sending it: the retry evaluated 20,919 tokens in 33.5
  seconds, the full cold rate, having kept nothing. That measurement
  corrected `public_message`, `.env.example`, the runbook and the errors
  table the same day and did not reach this file, so the classification the
  wire carries and the docstring explaining it disagreed for nineteen days.
  The prefix cache is real and does make an agent's *next* turn nearly free;
  it just does not survive a cancellation, and a cancellation is the only way
  this code is reached.
- read timeout after bytes flowed → `stream_interrupted`: the generation
  stalled mid-answer. The caller may hold a partial result, and whether to
  retry is their idempotence judgement, not ours.
"""

from __future__ import annotations

import httpx

from app.domain.exceptions import (
    NoAvailableModelError,
    RuntimeTimeoutError,
    StreamInterruptedError,
)


def timeout_error(
    runtime: str, ref: str, exc: httpx.TimeoutException, timeout: httpx.Timeout, *, mid_stream: bool
) -> NoAvailableModelError:
    if isinstance(exc, httpx.ConnectTimeout):
        return NoAvailableModelError(
            detail=f"{runtime} did not accept a connection for {ref} within "
            f"{timeout.connect}s; the runtime process may be down or overloaded"
        )
    if mid_stream:
        return StreamInterruptedError(
            detail=f"{runtime} went silent mid-stream for {ref}: no bytes for "
            f"{timeout.read}s after the generation had started"
        )
    return RuntimeTimeoutError(
        detail=f"{runtime} timed out for {ref} after {timeout.read}s without sending "
        f"a byte; the prompt may be too long to evaluate within the read timeout"
    )
