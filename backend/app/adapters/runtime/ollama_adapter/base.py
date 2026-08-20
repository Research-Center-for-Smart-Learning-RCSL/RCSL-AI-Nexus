"""Shared Ollama HTTP state and error translation."""

from __future__ import annotations

import httpx

from app.domain.exceptions import (
    ModelNotFoundError,
    NoAvailableModelError,
)


class OllamaRuntimeBase:
    _base_url: str
    _keep_alive: str | int
    _timeout: httpx.Timeout

    async def _raise_for_status(self, response: httpx.Response, ref: str) -> None:
        if response.status_code < 400:
            return
        # The body has to be read before it can be inspected on a streamed
        # response, and it goes to the log rather than to the caller: it can
        # name models and paths that a public caller should not learn about.
        await response.aread()
        detail = f"ollama returned {response.status_code} for {ref}: {response.text[:500]}"
        if response.status_code == 404:
            raise ModelNotFoundError(detail=detail)
        raise NoAvailableModelError(detail=detail)
