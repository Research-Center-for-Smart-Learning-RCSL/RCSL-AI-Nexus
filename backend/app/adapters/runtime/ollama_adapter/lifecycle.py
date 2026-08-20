"""Ollama model pull, load, unload, and residency lifecycle."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.adapters.runtime.validation import assert_valid_model_ref
from app.domain.entities.model import PullProgress, RuntimeResidency
from app.domain.exceptions import (
    DomainError,
    ModelNotFoundError,
    NoAvailableModelError,
)

from .base import OllamaRuntimeBase
from .decoding import _spellings
from .encoding import _set_num_ctx


class OllamaLifecycleMixin(OllamaRuntimeBase):
    async def pull(self, ref: str) -> AsyncGenerator[PullProgress, None]:
        """Stream download progress.

        Also an async generator: Ollama's pull endpoint answers with a stream
        of NDJSON progress objects, so a plain POST would report no progress
        and give no reliable completion signal.
        """
        assert_valid_model_ref(ref)

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream(
                "POST", "/api/pull", json={"model": ref, "stream": True}
            ) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("error"):
                        raise DomainError(detail=f"ollama pull failed: {event['error']}")

                    yield PullProgress(
                        status=event.get("status", ""),
                        completed_bytes=event.get("completed"),
                        total_bytes=event.get("total"),
                    )

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        """Warm a model into memory.

        An empty prompt with a keep_alive is Ollama's documented way to load
        without generating anything — but an embedding model refuses
        `/api/generate` outright (400, `"does not support generate"`), so that
        refusal is answered by warming through `/api/embed` with an empty
        input, which loads the weights and honours `keep_alive` the same way.
        Verified against Ollama on the Mac Studio: both directions, load and
        evict, behave identically to the generate path.
        """
        assert_valid_model_ref(ref)
        await self._post_lifecycle(ref, keep_alive=self._keep_alive, context_length=context_length)

    async def unload(self, ref: str) -> None:
        """Evict immediately. `keep_alive: 0` is the documented signal."""
        assert_valid_model_ref(ref)
        await self._post_lifecycle(ref, keep_alive=0)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(5.0)
            ) as client:
                response = await client.get("/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def residency(self) -> RuntimeResidency | None:
        """What Ollama is actually holding: `/api/ps` for resident models,
        `/api/tags` for what is on disk.

        Returns None when either call fails, because "could not ask" and
        "asked, and nothing is loaded" must not read the same: an unreachable
        runtime yielding an empty answer would mark every model unloaded on
        the strength of a network blip.

        Each model is recorded under Ollama's reported name and, when the tag
        is `:latest`, under the bare name as well — Ollama accepts both, the
        registry may hold either, and this aliasing is Ollama grammar that
        must not leak into the observer doing the matching.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=httpx.Timeout(10.0)
            ) as client:
                ps = await client.get("/api/ps")
                tags = await client.get("/api/tags")
                if ps.status_code != 200 or tags.status_code != 200:
                    return None
                resident_models = ps.json().get("models") or []
                on_disk_models = tags.json().get("models") or []
        except (httpx.HTTPError, json.JSONDecodeError):
            return None

        resident: dict[str, float] = {}
        for entry in resident_models:
            name = entry.get("name") or entry.get("model")
            if not name:
                continue
            gb = float(entry.get("size") or 0) / 1024**3
            for spelling in _spellings(name):
                resident[spelling] = gb

        on_disk: set[str] = set()
        for entry in on_disk_models:
            name = entry.get("name") or entry.get("model")
            if name:
                on_disk.update(_spellings(name))

        return RuntimeResidency(resident=resident, on_disk=frozenset(on_disk))

    async def _post_lifecycle(
        self, ref: str, keep_alive: str | int, context_length: int | None = None
    ) -> None:
        # The load is where Ollama sizes the runner, so this is the call that
        # decides how much memory the weights bring with them. An unload does
        # not size anything and passes nothing.
        options: dict[str, Any] = {}
        _set_num_ctx(options, context_length)
        body: dict[str, Any] = {"model": ref, "keep_alive": keep_alive}
        if options:
            body["options"] = options

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post("/api/generate", json=body)
            if response.status_code == 400:
                # An embedding model. The refusal is specific to generate;
                # embed with no input moves the same weights the same way.
                response = await client.post("/api/embed", json={**body, "input": []})
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(
                    detail=f"ollama lifecycle post returned {response.status_code} for {ref}"
                )
