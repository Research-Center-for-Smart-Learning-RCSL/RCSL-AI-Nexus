"""MLX pull, load, unload, residency, and lifecycle HTTP mapping."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.adapters.runtime.hf_validation import assert_valid_hf_repo_id
from app.domain.entities.model import PullProgress
from app.domain.exceptions import (
    ModelNotFoundError,
    ModelStateConflictError,
    NoAvailableModelError,
)

from .integrity import MlxIntegrityMixin


class MlxLifecycleMixin(MlxIntegrityMixin):
    async def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """Download a model into the host-shared HuggingFace cache, with progress.

        Unlike Ollama, there is no server endpoint to delegate to: the download
        runs here, in a worker thread, and progress is read by polling the cache
        directory while it runs. The bytes land under HF_HOME, which is a bind
        mount onto the host cache the native server reads.
        """
        assert_valid_hf_repo_id(ref)
        loop = asyncio.get_running_loop()

        total = await loop.run_in_executor(None, self._repo_total_bytes, ref)
        yield PullProgress(status="starting", completed_bytes=0, total_bytes=total)

        error: list[BaseException] = []

        def _run() -> None:
            try:
                self._download_snapshot(ref)
            except BaseException as exc:  # noqa: BLE001 - reported after the await
                error.append(exc)

        download = loop.run_in_executor(None, _run)
        while True:
            try:
                # `shield` so a poll-window timeout does not cancel the download
                # itself, only the wait on it.
                await asyncio.wait_for(asyncio.shield(download), timeout=self._pull_poll_interval)
                break
            except TimeoutError:
                completed = await loop.run_in_executor(None, self._downloaded_bytes, ref)
                yield PullProgress(
                    status="downloading", completed_bytes=completed, total_bytes=total
                )

        if error:
            raise self._map_hf_error(error[0], ref)
        yield PullProgress(status="success", completed_bytes=total, total_bytes=total)

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        """Warm the model into memory.

        `mlx_lm.server` loads on first use and has no dedicated load endpoint, so
        a one-token non-streaming completion is the way to force it resident
        without producing anything worth reading.

        `context_length` is accepted and not sent: the OpenAI-compatible surface
        `mlx_lm.server` exposes has no field for it, and MLX allocates its KV
        cache as the conversation grows rather than reserving it at load. The
        over-allocation this argument exists to prevent on Ollama therefore has
        no equivalent here — which is a property of this runtime rather than
        something left to do, so it is stated rather than raised.
        """
        assert_valid_hf_repo_id(ref)
        await self._post(
            "/v1/chat/completions",
            {"model": ref, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1},
            ref,
        )

    async def unload(self, ref: str) -> None:
        """Not supported: `mlx_lm.server` has no eviction endpoint.

        Raised rather than treated as a no-op on purpose. A silent success would
        move the registry to DOWNLOADED while the weights are still resident on
        the host, and the memory budget would then stop counting a model that is
        still occupying memory, admitting a later load that should be refused.
        The caller (ManageModels.unload) leaves the model LOADED on this error,
        which is the truthful state.
        """
        assert_valid_hf_repo_id(ref)
        raise ModelStateConflictError(
            detail=f"mlx_lm.server cannot unload {ref}; it is evicted when the server "
            "restarts or a different model is requested"
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(5.0)
            ) as client:
                response = await client.get("/v1/models")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def residency(self) -> None:
        """Cannot be observed: `mlx_lm.server` has no endpoint that says what
        is resident, only `/v1/models` listing what it could serve. None keeps
        the heartbeat trusting the registry's intent for MLX models, the same
        judgement `unload` and `embed` make — refusing to answer beats
        answering plausibly and wrongly."""
        return None

    async def _post(self, path: str, payload: dict[str, Any], ref: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(path, json=payload)
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(detail=f"mlx {path} returned {response.status_code}")
