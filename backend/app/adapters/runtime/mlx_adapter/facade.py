"""Port-facing MLX adapter facade."""

from __future__ import annotations

import httpx

from app.adapters.runtime.hf_validation import assert_valid_hf_repo_id

from .generation import MlxGenerationMixin
from .lifecycle import MlxLifecycleMixin


class MlxAdapter(MlxGenerationMixin, MlxLifecycleMixin):
    def __init__(
        self,
        base_url: str,
        request_timeout_seconds: int = 300,
        pull_poll_interval_seconds: float = 1.0,
        tool_calling_verified: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Whether somebody has watched this deployment's `mlx_lm.server` actually
        # execute a tool call. Default False, so an unverified deployment refuses
        # rather than answers. See `_assert_tools_are_verified`.
        self._tool_calling_verified = tool_calling_verified
        # A long read timeout because generation takes minutes, but a short
        # connect timeout so a host that is simply not there fails fast rather
        # than holding a concurrency slot for the whole request timeout.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(request_timeout_seconds), write=30.0, pool=5.0
        )
        # How often `pull` reports download progress. A constructor argument only
        # so a test can poll faster than once a second.
        self._pull_poll_interval = pull_poll_interval_seconds

    def validate_ref(self, ref: str) -> None:
        """MLX's grammar, exposed so the registry can refuse a repository id at
        the moment someone types it rather than at the first download."""
        assert_valid_hf_repo_id(ref)
