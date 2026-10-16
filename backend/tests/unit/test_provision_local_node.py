"""The local node row is rewritten from configuration on every deploy, so
everything it must keep has to come from configuration too (PR4b, #24)."""

from __future__ import annotations

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.provision import agent_node_mismatch, build_local_node


def test_the_agent_address_comes_from_configuration() -> None:
    """Activating PR4b, an `agent_url` set by hand was cleared by the next
    deploy's provisioning, and every chat request then found no runtime."""
    node = build_local_node(Settings(node_agent_url="http://node-agent:8100"))  # type: ignore[call-arg]

    assert node.agent_url == "http://node-agent:8100"


def test_without_an_agent_the_node_has_no_agent_address() -> None:
    assert build_local_node(Settings(node_agent_url="")).agent_url is None  # type: ignore[call-arg]
    assert build_local_node(Settings()).agent_url is None  # type: ignore[call-arg]


@pytest.mark.parametrize("url", [None, ""])
def test_an_enabled_agent_without_an_address_is_refused(url: str | None) -> None:
    """Review on #32: writing NULL left every chat request with no runtime."""
    settings = Settings(node_agent_enabled=True, node_agent_url=url)  # type: ignore[call-arg]

    with pytest.raises(ValueError, match="NODE_AGENT_URL"):
        build_local_node(settings)


def test_an_agent_claiming_another_node_is_reported() -> None:
    on = Settings(node_agent_enabled=True, node_id="mac-1")  # type: ignore[call-arg]
    off = Settings(node_id="mac-1")  # type: ignore[call-arg]

    assert agent_node_mismatch(on, {"NODE_AGENT_NODE_ID": "mac-2"}) == "mac-2"
    assert agent_node_mismatch(on, {"NODE_AGENT_NODE_ID": "mac-1"}) is None
    assert agent_node_mismatch(on, {}) is None
    assert agent_node_mismatch(off, {"NODE_AGENT_NODE_ID": "mac-2"}) is None
