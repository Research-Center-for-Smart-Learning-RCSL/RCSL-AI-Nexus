"""Index identity survives resolution, transport and per-batch revalidation."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.domain.entities.embedding import current_embedding_manifest
from app.domain.exceptions import NoAvailableModelError
from app.node_agent.dispatch import Completed, Sink
from app.node_agent.wire import EmbeddingRequest, Envelope, decode_embedding, encode_embedding
from tests.unit.test_node_agent_summary import summary_app


class EmbeddingCounter:
    def __init__(self, manifest: str = "manifest") -> None:
        self.manifest = manifest

    async def measure_capacity(self, ref: str) -> Measurement:
        return Measurement(self.manifest, None, 2048)


class EmbeddingRelay:
    def __init__(self) -> None:
        self.sends = 0

    def embed(self, payload: Any, **kwargs: Any) -> Any:
        async def run(sink: Sink) -> Completed:
            self.sends += 1
            sink.emit({"type": "embeddings", "data": [[0.1, 0.2]]})
            return Completed({"count": 1})

        return run


def test_optional_embedding_manifest_roundtrips_and_old_callers_remain_valid():
    envelope = Envelope("op", None, None, False)
    for pin in (None, "sha256:expected-weights"):
        wanted = EmbeddingRequest("nomic-embed-text", ("question",), pin)
        assert decode_embedding(encode_embedding(wanted, envelope)) == (wanted, envelope)


async def test_gateway_pin_changed_after_resolve_is_refused_before_any_embedding_send(monkeypatch):
    # The index and gateway resolved manifest-old, but the node has since been
    # repulled and consistently measured/re-pinned to its new manifest.
    counter, relay = EmbeddingCounter(), EmbeddingRelay()
    app = summary_app(monkeypatch, counter, relay)
    runtime = NodeAgentRuntime(
        "http://agent", "test-agent-token", timeout_s=5, transport=httpx.ASGITransport(app=app)
    )
    token = current_embedding_manifest.set("manifest-old")
    try:
        with pytest.raises(NoAvailableModelError, match="embedding_revision_mismatch"):
            await runtime.embed("nomic-embed-text", ["question"])
    finally:
        current_embedding_manifest.reset(token)
    assert relay.sends == 0 and not app.state.agent.store.ops


async def test_matching_index_manifest_reaches_agent_and_settles_normally(monkeypatch):
    relay = EmbeddingRelay()
    app = summary_app(monkeypatch, EmbeddingCounter(), relay)
    runtime = NodeAgentRuntime(
        "http://agent", "test-agent-token", timeout_s=5, transport=httpx.ASGITransport(app=app)
    )
    token = current_embedding_manifest.set("manifest")
    try:
        assert await runtime.embed("nomic-embed-text", ["question"]) == [[0.1, 0.2]]
    finally:
        current_embedding_manifest.reset(token)
    assert relay.sends == 1
    assert list(app.state.agent.store.ops.values())[0].kind == "embedding_batch"
