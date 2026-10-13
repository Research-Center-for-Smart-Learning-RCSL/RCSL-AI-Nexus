"""A read-only routing rehearsal. No inference, warming or repair is performed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.capability import ROUTABLE_CAPABILITIES
from app.domain.entities.model import Model
from app.domain.entities.node import Node
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.exceptions import NoAvailableModelError
from app.domain.services.routing_service import RoutingService
from app.shared.clock import FixedClock


@dataclass(frozen=True)
class CapabilityAvailability:
    capability: str
    enabled: bool
    available: bool
    reasons: tuple[str, ...]


def assess_availability(
    policies: list[RoutingPolicy],
    models: list[Model],
    nodes: list[Node],
    unresolved: dict[str, int],
    unavailable_models: frozenset[str],
    now: datetime,
) -> list[CapabilityAvailability]:
    """Use inference's selector, then check its selected adapter and node gate.

    Missing policies are reported but not enabled or alerted: a deployment
    need not offer every capability. Reasons contain no inventory identifiers.
    Memory-constrained policies get the same unknown-memory refusal as the
    current inference callers, which also supply no free-memory snapshot.
    """
    routing = RoutingService(FixedClock(now))
    by_policy = {p.capability: p for p in policies}
    by_node = {n.id: n for n in nodes}
    by_model = {m.alias: m for m in models}
    result = []
    for capability in sorted(ROUTABLE_CAPABILITIES):
        policy = by_policy.get(capability)
        if policy is None:
            result.append(CapabilityAvailability(capability, False, False, ("no_policy",)))
            continue
        try:
            selected = routing.select(policy, by_model, by_node)
        except NoAvailableModelError:
            reasons = set()
            for candidate in policy.candidates:
                model = by_model.get(candidate.model_alias)
                node = by_node.get(model.node_id) if model else None
                if model is None:
                    reasons.add("model_missing")
                elif node is None:
                    reasons.add("node_missing")
                elif unresolved.get(node.id, 0):
                    reasons.add("node_operation_unresolved")
                elif model.id in unavailable_models:
                    reasons.add("runtime_unavailable")
                else:
                    reason = routing.rejection(candidate.require, model, node, None, now)
                    if reason:
                        reasons.add(reason)
            result.append(
                CapabilityAvailability(
                    capability, True, False, tuple(sorted(reasons or {"no_eligible_model"}))
                )
            )
        else:
            # The gateway does not retry selection with a blocked node or a
            # missing adapter removed. Doing so only here would report a
            # usable fallback while the real request still receives 503.
            gates = []
            if unresolved.get(selected.node_id, 0):
                gates.append("node_operation_unresolved")
            if selected.id in unavailable_models:
                gates.append("runtime_unavailable")
            result.append(CapabilityAvailability(capability, True, not gates, tuple(gates)))
    return result
