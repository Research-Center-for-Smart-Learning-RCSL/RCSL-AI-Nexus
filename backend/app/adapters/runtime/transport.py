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
  outran the read timeout. An immediate retry usually succeeds, because the
  prompt is now in the runtime's prefix cache and evaluation is nearly free
  the second time.
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
