"""Port-facing Ollama adapter facade."""

from __future__ import annotations

import httpx

from app.adapters.runtime.validation import assert_valid_model_ref

from .encoding import DEFAULT_KEEP_ALIVE, _keep_alive
from .generation import OllamaGenerationMixin
from .lifecycle import OllamaLifecycleMixin


class OllamaAdapter(OllamaGenerationMixin, OllamaLifecycleMixin):
    def __init__(
        self,
        base_url: str,
        request_timeout_seconds: int = 300,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._keep_alive = _keep_alive(keep_alive)
        # Generation legitimately takes minutes, so the read timeout is long,
        # but a host that is simply not there must fail fast rather than
        # holding a concurrency slot for the full request timeout.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(request_timeout_seconds), write=30.0, pool=5.0
        )

    def validate_ref(self, ref: str) -> None:
        """Ollama's grammar, exposed so the registry can refuse a reference at
        the moment someone types it rather than at the first download."""
        assert_valid_model_ref(ref)
