"""The local node row is rewritten from configuration on every deploy, so
everything it must keep has to come from configuration too (PR4b, #24)."""

from __future__ import annotations

from app.infrastructure.config import Settings
from app.infrastructure.provision import build_local_node


def test_the_agent_address_comes_from_configuration() -> None:
    """Activating PR4b, an `agent_url` set by hand was cleared by the next
    deploy's provisioning, and every chat request then found no runtime."""
    node = build_local_node(Settings(node_agent_url="http://node-agent:8100"))  # type: ignore[call-arg]

    assert node.agent_url == "http://node-agent:8100"


def test_without_an_agent_the_node_has_no_agent_address() -> None:
    assert build_local_node(Settings(node_agent_url="")).agent_url is None  # type: ignore[call-arg]
    assert build_local_node(Settings()).agent_url is None  # type: ignore[call-arg]
