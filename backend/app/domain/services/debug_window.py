"""The bound on the one control that makes the platform reveal more.

While a debug window is open, error responses to that credential carry
`error.detail` — the operator-facing string that is otherwise log-only, and
the single deliberate exception to "no internal detail in responses"
(security.md section 5 and `interfaces/http/errors.py`).

The ceiling lives here rather than on either use case because there are two
credentials it applies to and they must not drift. `debug_logging_until`
exists on **both** the API key and the user row, and security.md section 9.2
gives the reason the second is not redundant: *the management chat path has no
API key attached*. An administrator debugging the admin UI is authenticated by
a session, so the key-side window — the only one that existed until
2026-08-05 — could not be opened for them at all.

A ceiling rather than a caller's promise is what keeps "time-boxed" a property
of the mechanism. The window is also audited on both sides, because the record
of who widened what the platform reveals belongs beside the record of what it
then revealed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.exceptions import ModelStateConflictError

MAX_DEBUG_WINDOW_MINUTES = 24 * 60
"""A day. Long enough to span a working session, short enough that forgetting
about it is not a permanent change to what the platform discloses."""


def debug_window_until(now: datetime, minutes: int) -> datetime | None:
    """Resolve a requested window to an expiry, or None for "closed".

    Zero is not an error: it is how the window is closed, so that opening and
    closing are the same verb and the audit trail carries both.
    """
    if not 0 <= minutes <= MAX_DEBUG_WINDOW_MINUTES:
        raise ModelStateConflictError(
            detail=f"debug window must be 0..{MAX_DEBUG_WINDOW_MINUTES} minutes"
        )
    return now + timedelta(minutes=minutes) if minutes else None
