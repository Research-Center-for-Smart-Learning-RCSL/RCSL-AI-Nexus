from __future__ import annotations

import pytest

from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.exceptions import NoAvailableModelError
from app.domain.services.routing_service import RoutingService


def make_model(alias: str, state: ModelState = ModelState.LOADED, node_id: str = "n1") -> Model:
    return Model(
        id=f"id-{alias}",
        alias=alias,
        ref=f"{alias}:latest",
        runtime=RuntimeKind.OLLAMA,
        node_id=node_id,
        state=state,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=8.0, context_length=8192),
    )


def make_node(node_id: str = "n1", status: NodeStatus = NodeStatus.ONLINE) -> Node:
    return Node(
        id=node_id,
        name=node_id,
        address="100.64.0.1",
        status=status,
        total_memory_gb=64.0,
    )


@pytest.fixture
def service() -> RoutingService:
    return RoutingService()


def test_picks_highest_priority_candidate(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate("fallback", priority=10),
            RoutingCandidate("primary", priority=100),
        ),
    )
    models = {"primary": make_model("primary"), "fallback": make_model("fallback")}

    assert service.select(policy, models, {"n1": make_node()}).alias == "primary"


def test_falls_back_when_requirement_not_met(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate(
                "primary",
                priority=100,
                require=Requirement(model_state=frozenset({ModelState.LOADED})),
            ),
            RoutingCandidate("fallback", priority=10),
        ),
    )
    models = {
        "primary": make_model("primary", state=ModelState.NOT_DOWNLOADED),
        "fallback": make_model("fallback"),
    }

    assert service.select(policy, models, {"n1": make_node()}).alias == "fallback"


def test_skips_candidate_on_offline_node(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate(
                "primary",
                priority=100,
                require=Requirement(node_status=frozenset({NodeStatus.ONLINE})),
            ),
            RoutingCandidate("fallback", priority=10),
        ),
    )
    models = {
        "primary": make_model("primary", node_id="down"),
        "fallback": make_model("fallback", node_id="n1"),
    }
    nodes = {"down": make_node("down", NodeStatus.OFFLINE), "n1": make_node("n1")}

    assert service.select(policy, models, nodes).alias == "fallback"


def test_missing_model_or_node_is_skipped_not_fatal(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate("never-registered", priority=100),
            RoutingCandidate("orphaned", priority=50),
            RoutingCandidate("good", priority=10),
        ),
    )
    models = {"orphaned": make_model("orphaned", node_id="gone"), "good": make_model("good")}

    assert service.select(policy, models, {"n1": make_node()}).alias == "good"


def test_raises_when_nothing_qualifies(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate(
                "primary",
                priority=100,
                require=Requirement(model_state=frozenset({ModelState.LOADED})),
            ),
        ),
    )
    models = {"primary": make_model("primary", state=ModelState.ERROR)}

    with pytest.raises(NoAvailableModelError) as exc:
        service.select(policy, models, {"n1": make_node()})

    # The public message must not disclose which models were considered.
    assert "primary" not in exc.value.public_message


def test_min_free_memory_requirement(service: RoutingService) -> None:
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate("big", priority=100, require=Requirement(min_free_memory_gb=32.0)),
            RoutingCandidate("small", priority=10),
        ),
    )
    models = {"big": make_model("big"), "small": make_model("small")}

    chosen = service.select(policy, models, {"n1": make_node()}, free_memory_gb={"n1": 4.0})
    assert chosen.alias == "small"
