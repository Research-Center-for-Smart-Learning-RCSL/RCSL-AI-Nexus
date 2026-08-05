"""Diagnostics both runtime adapters attach to a transport timeout.

One function rather than a string in each adapter, because the string encodes a
diagnosis and the first version diagnosed wrongly: every `httpx.TimeoutException`
was described as "without sending a byte; the prompt may be too long to
evaluate", which is true of exactly one of the three ways a timeout happens.
Told that a runtime whose process is down (connect timeout) or one that stalled
half way through an answer (read timeout mid-stream) had been reading a long
prompt, an operator debugs the wrong thing. The status stays 503 in every case —
the remedy really is retry-or-give-up — it is the log line that has to tell the
three apart, because the log line is what decides where the operator looks.
"""

from __future__ import annotations

import httpx


def timeout_detail(
    runtime: str, ref: str, exc: httpx.TimeoutException, timeout: httpx.Timeout, *, mid_stream: bool
) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return (
            f"{runtime} did not accept a connection for {ref} within "
            f"{timeout.connect}s; the runtime process may be down or overloaded"
        )
    if mid_stream:
        return (
            f"{runtime} went silent mid-stream for {ref}: no bytes for "
            f"{timeout.read}s after the generation had started"
        )
    return (
        f"{runtime} timed out for {ref} after {timeout.read}s without sending "
        f"a byte; the prompt may be too long to evaluate within the read timeout"
    )
