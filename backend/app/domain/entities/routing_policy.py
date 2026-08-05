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
    thinking: bool | None = None
    """Whether a request that expresses no preference gets deliberation.

    Per capability rather than per deployment, because that is the level the
    answer actually varies at. `chat` wants a model to think; `assist` sits
    beside a settings form where a model that spends its whole budget
    deliberating produces no answer at all; and an agent client on `code` pays
    that cost again on every tool round trip, which is the case this field was
    added for. It is not per *model*, because one resident copy serves every
    capability that routes to it (`ix_models_node_ref` is unique on node,
    runtime and ref) and the memory budget could not afford a second.

    `None` means the policy expresses no preference and the deployment default
    applies, which is what every existing policy has. Only the request may
    override it. See `RouteChatRequest._resolve_thinking`.
    """
