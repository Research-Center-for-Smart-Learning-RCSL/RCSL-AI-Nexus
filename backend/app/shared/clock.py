"""Time as an injected dependency.

Use cases that stamp records or check expiry take a `Clock` rather than
calling `datetime.now()` directly, so their behaviour around expiry
boundaries is testable without freezing global state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test double."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._at = self._at + timedelta(seconds=seconds)
