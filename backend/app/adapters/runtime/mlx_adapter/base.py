"""Shared MLX HTTP state and error translation."""

from __future__ import annotations

import httpx

from app.domain.exceptions import (
    ModelNotFoundError,
    NoAvailableModelError,
)


class MlxRuntimeBase:
    _base_url: str
    _timeout: httpx.Timeout
    _pull_poll_interval: float
    _tool_calling_verified: bool

    async def _raise_for_status(self, response: httpx.Response, ref: str) -> None:
        if response.status_code < 400:
            return
        # The body has to be read before it can be inspected on a streamed
        # response, and it goes to the log rather than to the caller: it can name
        # models and paths a public caller should not learn about.
        await response.aread()
        detail = f"mlx returned {response.status_code} for {ref}: {response.text[:500]}"
        if response.status_code == 404:
            raise ModelNotFoundError(detail=detail)
        raise NoAvailableModelError(detail=detail)
