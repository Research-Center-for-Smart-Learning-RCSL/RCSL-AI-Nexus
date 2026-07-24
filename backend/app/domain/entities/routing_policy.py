"""Capability to model mapping.

`Requirement` is a closed dataclass of structured fields, never an expression
string. Routing policies are editable through the admin UI and evaluated
inside the gateway process, so an expression evaluator would turn "edit a
routing policy" into "execute arbitrary code in the gateway". Adding a new
condition means adding a field and a comparison, which is a reviewable code
change. See docs/ARCHITECTURE.md section 2.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.model import ModelState
from app.domain.entities.node import NodeStatus


@dataclass(frozen=True, slots=True)
class Requirement:
    node_status: frozenset[NodeStatus] = field(default_factory=frozenset)
    model_state: frozenset[ModelState] = field(default_factory=frozenset)
    min_free_memory_gb: float | None = None


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    model_alias: str
    priority: int
    require: Requirement = Requirement()


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    capability: str
    candidates: tuple[RoutingCandidate, ...]
