"""Authenticated capacity reads are available without runtime dispatch."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.node_agent.api import create_app
from tests.unit.exact_token_counting_fixtures import write_store


async def test_capacity_reads_the_agents_weights_without_building_a_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "blobs").mkdir()
    write_store(tmp_path, context_length=4096)
    counter = GgufTokenCounter(tmp_path)

    async def forbidden(*args):
        raise AssertionError("capacity read built a vocabulary")

    monkeypatch.setattr(counter, "_vocabulary", forbidden)
    app = create_app()
    app.state.agent = SimpleNamespace(
        settings=SimpleNamespace(token="capacity-token"), counter=counter
    )
    # No relay or dispatcher exists: the endpoint must be genuinely read-only.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://agent"
    ) as client:
        denied = await client.get("/v1/model-capacity", params={"ref": "primary:latest"})
        assert denied.status_code == 401
        response = await client.get(
            "/v1/model-capacity",
            params={"ref": "primary:latest"},
            headers={"Authorization": "Bearer capacity-token"},
        )
    assert response.status_code == 200
    result = response.json()
    assert result["declared_context_length"] == 4096
    assert isinstance(result["manifest_digest"], str) and len(result["manifest_digest"]) == 64


async def test_missing_model_store_returns_unresolved_capacity() -> None:
    app = create_app()
    app.state.agent = SimpleNamespace(
        settings=SimpleNamespace(token="capacity-token"), counter=None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://agent"
    ) as client:
        response = await client.get(
            "/v1/model-capacity",
            params={"ref": "primary:latest"},
            headers={"Authorization": "Bearer capacity-token"},
        )
    assert response.json() == {
        "manifest_digest": None,
        "declared_context_length": None,
        "embedding_manifest_pin": True,
    }
