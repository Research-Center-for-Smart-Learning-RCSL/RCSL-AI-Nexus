"""Capability to model resolution.

The core of the platform, and deliberately pure: no I/O, no clock, no
randomness. Everything it needs is passed in, which makes the whole of the
routing behaviour unit testable in milliseconds without a database or a
runtime.
"""

from __future__ import annotations

from app.domain.entities.model import Model
from app.domain.entities.node import Node
from app.domain.entities.routing_policy import Requirement, RoutingPolicy
from app.domain.exceptions import NoAvailableModelError


class RoutingService:
    def select(
        self,
        policy: RoutingPolicy,
        models_by_alias: dict[str, Model],
        nodes_by_id: dict[str, Node],
        free_memory_gb: dict[str, float] | None = None,
    ) -> Model:
        """Return the highest-priority candidate whose requirements hold.

        Raises `NoAvailableModelError` if none qualify. That error does not
        name the candidates it considered, so a public caller learns nothing
        about the model inventory.
        """
        free_memory_gb = free_memory_gb or {}

        for candidate in sorted(policy.candidates, key=lambda c: -c.priority):
            model = models_by_alias.get(candidate.model_alias)
            if model is None:
                continue
            node = nodes_by_id.get(model.node_id)
            if node is None:
                continue
            if self._satisfies(candidate.require, model, node, free_memory_gb.get(node.id)):
                return model

        raise NoAvailableModelError(detail=f"capability={policy.capability}")

    def _satisfies(
        self,
        require: Requirement,
        model: Model,
        node: Node,
        free_memory: float | None,
    ) -> bool:
        """Structured field comparison only.

        No eval, no exec, no expression evaluator, no template engine.
        Routing policies are editable through the admin UI and evaluated
        inside the gateway process, so an expression language here would turn
        policy editing into remote code execution. Adding a condition means
        adding a field and a branch, which is a reviewable code change.
        """
        if require.node_status and node.status not in require.node_status:
            return False
        if require.model_state and model.state not in require.model_state:
            return False
        if require.min_free_memory_gb is not None:
            if free_memory is None or free_memory < require.min_free_memory_gb:
                return False
        return True
