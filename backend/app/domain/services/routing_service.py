"""Capability to model resolution.

No I/O or randomness. An injectable clock checks the age of residency
evidence; the same selector drives inference and the availability rehearsal.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.entities.model import Model, ModelState, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingPolicy
from app.domain.exceptions import NoAvailableModelError
from app.shared.clock import Clock, SystemClock

RESIDENCY_MAX_AGE_SECONDS = 90


class RoutingService:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

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
        now = self._clock.now()

        for candidate in sorted(policy.candidates, key=lambda c: -c.priority):
            model = models_by_alias.get(candidate.model_alias)
            if model is None:
                continue
            node = nodes_by_id.get(model.node_id)
            if node is None:
                continue
            if (
                self.rejection(candidate.require, model, node, free_memory_gb.get(node.id), now)
                is None
            ):
                return model

        raise NoAvailableModelError(detail=f"capability={policy.capability}")

    def rejection(
        self,
        require: Requirement,
        model: Model,
        node: Node,
        free_memory: float | None,
        now: datetime,
    ) -> str | None:
        """Structured field comparison only.

        No eval, no exec, no expression evaluator, no template engine.
        Routing policies are editable through the admin UI and evaluated
        inside the gateway process, so an expression language here would turn
        policy editing into remote code execution. Adding a condition means
        adding a field and a branch, which is a reviewable code change.
        """
        if node.status is not NodeStatus.ONLINE:
            return "node_unhealthy"
        if require.node_status and node.status not in require.node_status:
            return "node_unhealthy"
        # Ollama can report residency. Missing, future or stale evidence must
        # never turn an old load intent into a demand load after a restart.
        # MLX and the other adapters currently cannot report it.
        if model.runtime is RuntimeKind.OLLAMA:
            if model.observed_state is None or model.observed_at is None:
                return "residency_unknown"
            age = (now - model.observed_at).total_seconds()
            if not 0 <= age <= RESIDENCY_MAX_AGE_SECONDS:
                return "residency_stale"
            if model.observed_state is not ModelState.LOADED:
                return "model_not_resident"
        if require.model_state:
            # Intent fallback is only reachable for unobservable runtimes.
            effective = model.observed_state or model.state
            if effective not in require.model_state:
                return "model_state_mismatch"
        if require.min_free_memory_gb is not None:
            if free_memory is None or free_memory < require.min_free_memory_gb:
                return "insufficient_memory"
        return None
