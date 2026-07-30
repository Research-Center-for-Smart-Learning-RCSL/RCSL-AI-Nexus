"""MLX runtime adapter.

Talks to an `mlx_lm.server` running natively on the macOS host, reached through
`host.docker.internal`, because containers on macOS cannot use the GPU (the whole
reason MLX exists here rather than a containerised runtime). See
docs/ARCHITECTURE.md section 0.1.

MLX is the second runtime, and adding it is the real test of whether the
hexagonal layering paid off: this file, one entry in `build_runtimes`, and one
setting, with no use case and no interface touched. Two things about MLX are
genuinely unlike Ollama and are handled here rather than papered over:

- `mlx_lm.server` has no download-with-progress endpoint. Ollama's daemon pulls
  on the host and streams NDJSON progress back; MLX models are HuggingFace
  snapshots. So `pull` downloads via `huggingface_hub` into the cache the host
  server reads (shared into this container as a bind mount, HF_HOME), and reports
  real byte progress by polling that cache while the download runs in a worker
  thread. The download is file I/O, not GPU work, so running it in the container
  does not contradict section 0.1; only the bytes' destination matters, and that
  is a host path.
- `mlx_lm.server` has no explicit unload. `unload` therefore raises rather than
  reporting success, because reporting success would tell the registry the
  weights were freed while they are still resident, and the memory budget would
  then stop counting a model that is still occupying the host. That is exactly
  the over-commit the section 4.3 budget exists to prevent.

Everything on the inference path goes over the OpenAI-compatible HTTP API.
Nothing builds a shell command, and every reference passes `assert_valid_hf_repo_id`
first. `huggingface_hub` is imported lazily inside the methods that download, so
the inference path neither pays its import cost nor depends on it being present.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx

from app.adapters.runtime.hf_validation import assert_valid_hf_repo_id
from app.domain.entities.chat import CompletionChunk, Message
from app.domain.entities.model import PullProgress
from app.domain.exceptions import (
    DomainError,
    ModelNotFoundError,
    ModelStateConflictError,
    NoAvailableModelError,
    RuntimeCapabilityError,
)

logger = logging.getLogger(__name__)

# OpenAI clients branch on finish_reason, so a value they do not recognise reads
# as a protocol error. Only the two the domain acts on are passed through; MLX
# emits no others today, but an unexpected one is reported as "stop" rather than
# forwarded.
_FINISH_REASONS = {"stop": "stop", "length": "length"}


def _finish_reason(reason: str | None) -> str:
    return _FINISH_REASONS.get(reason or "stop", "stop")


class MlxAdapter:
    def __init__(
        self,
        base_url: str,
        request_timeout_seconds: int = 300,
        pull_poll_interval_seconds: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # A long read timeout because generation takes minutes, but a short
        # connect timeout so a host that is simply not there fails fast rather
        # than holding a concurrency slot for the whole request timeout.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(request_timeout_seconds), write=30.0, pool=5.0
        )
        # How often `pull` reports download progress. A constructor argument only
        # so a test can poll faster than once a second.
        self._pull_poll_interval = pull_poll_interval_seconds

    # --- inference -------------------------------------------------------

    def validate_ref(self, ref: str) -> None:
        """MLX's grammar, exposed so the registry can refuse a repository id at
        the moment someone types it rather than at the first download."""
        assert_valid_hf_repo_id(ref)

    async def generate(
        self,
        ref: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        thinking: bool = True,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream a completion over the OpenAI-compatible endpoint.

        An async generator, declared without `async def` in the port and called
        without await. The `finally` the `async with` provides is what closes the
        upstream request when a client disconnects; without it the server keeps
        generating for someone who has already gone.

        `thinking` is accepted and ignored. `mlx_lm.server` speaks the OpenAI
        chat schema, which has no field for suppressing deliberation, and a
        model that reasons does so inside `content` where this adapter cannot
        separate it. Silently accepting the argument is deliberate: the caller
        asks the port, not the runtime, and a runtime that cannot honour the
        request is not a reason to refuse the generation.
        """
        assert_valid_hf_repo_id(ref)
        payload: dict[str, Any] = {
            "model": ref,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": True,
            # Ask for a usage total in the terminal frame. If the server does not
            # honour it, the per-chunk counts below still stand.
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            # Stopping at the source beats cutting the stream: the model stops
            # generating rather than producing tokens nobody reads.
            payload["max_tokens"] = max_tokens

        counted = 0
        finish_reason: str | None = None
        usage_tokens: int | None = None
        saw_terminal = False

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
                await self._raise_for_status(response, ref)

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        saw_terminal = True
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning("mlx emitted a non-JSON SSE line, ignoring")
                        continue

                    if event.get("error"):
                        raise NoAvailableModelError(detail=f"mlx: {event['error']}")

                    choices = event.get("choices") or []
                    if choices:
                        choice = choices[0]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        if delta:
                            # Counted one apiece as they arrive, so a disconnect
                            # still bills what was produced. Reconciled against
                            # the server's own total, if it sends one, below.
                            counted += 1
                            yield CompletionChunk(delta=delta, token_count=1)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                            saw_terminal = True

                    usage = event.get("usage")
                    if usage and usage.get("completion_tokens") is not None:
                        usage_tokens = int(usage["completion_tokens"])

        if not saw_terminal:
            # The stream ended without [DONE] or a finish_reason: the server
            # restarted, the model was evicted, or the read timeout fired.
            # Returning quietly would let the caller record a complete generation
            # and report "stop" to the client.
            raise NoAvailableModelError(
                detail=f"mlx stream for {ref} ended without a terminal frame"
            )

        # The authoritative token count arrives only at the end, so emit the
        # difference here. Emitting the whole figure would double-count every
        # token already streamed.
        correction = 0
        if usage_tokens is not None:
            correction = usage_tokens - counted
            if correction < 0:
                logger.info(
                    "mlx completion_tokens=%s below chunk count=%s for %s",
                    usage_tokens,
                    counted,
                    ref,
                )
                correction = 0
        yield CompletionChunk(
            delta="", finish_reason=_finish_reason(finish_reason), token_count=correction
        )

    # --- model lifecycle -------------------------------------------------

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

    async def load(self, ref: str) -> None:
        """Warm the model into memory.

        `mlx_lm.server` loads on first use and has no dedicated load endpoint, so
        a one-token non-streaming completion is the way to force it resident
        without producing anything worth reading.
        """
        assert_valid_hf_repo_id(ref)
        await self._post(
            "/v1/chat/completions",
            {"model": ref, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1},
            ref,
        )

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        """Not supported: `mlx_lm.server` serves completions only.

        Refused rather than approximated, which is the same judgement `unload`
        below makes. A plausible-looking vector from the wrong source would not
        fail: it would index the knowledge base with values that retrieve
        confidently and wrongly, and nothing downstream could tell. The routing
        policy for the `embedding` capability should name an Ollama model until
        there is an MLX embedding server to point at.
        """
        assert_valid_hf_repo_id(ref)
        raise RuntimeCapabilityError(
            detail=f"mlx_lm.server has no embeddings endpoint; {ref} cannot embed"
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

    # --- internals -------------------------------------------------------
    #
    # The three download seams are methods so tests can replace them without a
    # network or a GPU, and so the heavy `huggingface_hub` import is paid only
    # when a download actually runs.

    def _download_snapshot(self, ref: str) -> None:
        from huggingface_hub import snapshot_download

        # cache_dir left to HF_HOME so the bytes land where the host server reads.
        snapshot_download(repo_id=ref)

    def _repo_total_bytes(self, ref: str) -> int | None:
        from huggingface_hub import HfApi

        info = HfApi().model_info(ref, files_metadata=True)
        sizes = [s.size for s in (info.siblings or []) if s.size]
        return sum(sizes) if sizes else None

    def _downloaded_bytes(self, ref: str) -> int:
        from huggingface_hub import repo_folder_name
        from huggingface_hub.constants import HF_HUB_CACHE

        root = Path(HF_HUB_CACHE) / repo_folder_name(repo_id=ref, repo_type="model")
        if not root.exists():
            return 0
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

    def _map_hf_error(self, exc: BaseException, ref: str) -> DomainError:
        try:
            from huggingface_hub.utils import (  # type: ignore[attr-defined]
                GatedRepoError,
                RepositoryNotFoundError,
            )
        except ImportError:
            return DomainError(detail=f"mlx pull failed for {ref}: {exc}")

        if isinstance(exc, RepositoryNotFoundError):
            return ModelNotFoundError(detail=f"{ref} is not present on the hub")
        if isinstance(exc, GatedRepoError):
            return NoAvailableModelError(detail=f"{ref} is gated and needs authorisation")
        return DomainError(detail=f"mlx pull failed for {ref}: {exc}")

    async def _post(self, path: str, payload: dict[str, Any], ref: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(path, json=payload)
            if response.status_code == 404:
                raise ModelNotFoundError(detail=f"{ref} is not present on this runtime")
            if response.status_code >= 400:
                raise NoAvailableModelError(detail=f"mlx {path} returned {response.status_code}")

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
